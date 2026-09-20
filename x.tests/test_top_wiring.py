"""Toda entrada del monitor tiene que estar CONDUCIDA en el top.

El fallo que motiva esto: `mem_read_word` --la palabra de 32 bits que contesta
READ_WORD-- estaba declarada en el top de la 10 y de la 16, conectada al
monitor, y **no la conducia nadie**. El adaptador ya producia el valor; sólo
faltaba el cable. En placa, READ_WORD devolvia una X.

Por qué no lo vio ninguna prueba, que es la parte interesante: `monitor_tb`
prueba el monitor contra una memoria falsa, y ahí `mem_read_word` es un `reg`
del propio banco, que el banco conduce. O sea que la señal siempre tenía valor
en simulación justamente porque el banco suplía lo que al top le faltaba. Y
ningún testbench de esas carpetas instancia `top`, así que su cableado no se
simulaba en ninguna parte.

De ahí la forma de esta prueba. No simula: lee el RTL y comprueba que cada
señal que entra al monitor sale de algún sitio -- un `assign`, la salida de
otro módulo, o un `always`. Es barato, cubre las diez carpetas, y ataca
exactamente el hueco que dejan los bancos de unidad.

SEGUNDA FAMILIA DE FALLOS: LOS ANCHOS. Misma causa --ningún banco instancia
`top`-- y un síntoma todavía peor, porque Verilog no avisa. La 18 declaraba
doce bits de dirección en el decodificador y cinco en su `top.v`; al conectar
el puerto, Verilog truncó **en silencio** y los dieciséis dispositivos cayeron
todos sobre el de vídeo: pedir `SYS_ID` devolvía `FB_FRONT`.

No hay warning, no hay error, no hay simulación que lo vea. Lo único que lo
detecta sin sintetizar es comparar el ancho declarado de cada señal con el del
puerto al que se conecta, que es lo que hace `AnchosDePuertoTest`. Importa
especialmente ahora: MMIO v2 separa los dispositivos por megabytes, así que
ese bus de direcciones se ensancha en las diez carpetas.

Una conexión con un `[a:b]` explícito NO es un fallo aunque no ocupe el puerto
entero: es una decisión escrita. Lo que se persigue es el nombre desnudo cuyo
ancho no coincide, que es truncamiento accidental.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROTOTIPOS = ("6.fpga-cpu", "10.fpga-cpu-ram", "12.fpga-gpu", "14.fpga-gpu-ram",
              "16.fpga-cpu-hdmi", "17.fpga-gpu-ram-v2", "18.fpga-cpu-hdmi-bl8",
              "19.fpga-cpu-hdmi-ls", "21.fpga-cpu-hdmi-alu", "22.fpga-gpu-bl8")

# Las entradas del monitor que traen DATOS de vuelta. Las de control
# (`clk`, `reset`) las conduce el reloj y no hace falta mirarlas.
ENTRADAS = ("mem_read_data", "mem_read_word", "mem_ready", "mem_error",
            "cpu_halted", "cpu_pc", "cpu_debug_register_data")


def _cerrar(texto: str, desde: int) -> int:
    """Índice tras el paréntesis que cierra el abierto en `desde`."""
    profundidad, cursor = 1, desde
    while profundidad and cursor < len(texto):
        profundidad += {"(": 1, ")": -1}.get(texto[cursor], 0)
        cursor += 1
    return cursor


def puertos_del_monitor(texto: str) -> dict:
    """{puerto: señal} de la instanciación de `monitor` en este fichero.

    Los paréntesis se equilibran en vez de buscar el primer cierre: la familia
    GPU instancia el monitor CON PARÁMETROS --`.VERSION_MAJOR(8'h02)`, cinco
    ventanas...-- y un `[^)]*` se corta dentro del primero de ellos. Con eso
    esta prueba sólo miraba las seis carpetas de CPU y decía que todo bien.
    """
    con_parametros = re.search(r"\bmonitor\s*#\s*\(", texto)
    if con_parametros:
        # Saltar la lista de parámetros entera y buscar la de puertos detrás.
        tras_parametros = _cerrar(texto, con_parametros.end())
        # Entre el cierre de los parámetros y el nombre de la instancia puede
        # haber un COMENTARIO, y lo hay en cuanto las ventanas se anotan una a
        # una: `...WINDOW3_END(...))  // CPU PERF`. Con un `\s*` a secas esto
        # no casaba, `puertos_del_monitor` devolvía {} y la carpeta se saltaba
        # ENTERA sin decir nada -- que es justo el fallo silencioso que este
        # fichero existe para cazar, cometido por él. La 21 llevaba saltándose
        # desde su propia migración.
        siguiente = re.compile(r"(?:\s|//[^\n]*\n|/\*.*?\*/)*\w+\s*\(",
                               re.S).match(texto, tras_parametros)
        if not siguiente:
            return {}
        inicio = siguiente.end()
    else:
        simple = re.search(r"\bmonitor\s+\w+\s*\(", texto)
        if not simple:
            return {}
        inicio = simple.end()
    cursor = _cerrar(texto, inicio)
    lista = texto[inicio:cursor]
    return {p: s for p, s in re.findall(r"\.(\w+)\s*\(\s*([\w\[\]:]+)\s*\)", lista)}


def esta_conducida(texto: str, senal: str, sin: str) -> bool:
    """¿Sale `senal` de algún sitio, aparte de entrar al monitor?"""
    resto = texto.replace(sin, "")
    return bool(
        re.search(rf"\bassign\s+{re.escape(senal)}\b", resto)
        # salida de otro módulo: .lo_que_sea(senal)
        or re.search(rf"\.\w+\s*\(\s*{re.escape(senal)}\s*\)", resto)
        or re.search(rf"\b{re.escape(senal)}\s*<=", resto)
        or re.search(rf"\b{re.escape(senal)}\s*=", resto)
    )


class CableadoDelTopTest(unittest.TestCase):
    def test_toda_entrada_del_monitor_sale_de_algun_sitio(self):
        revisados = 0
        for prototipo in PROTOTIPOS:
            for top in sorted((ROOT / prototipo).glob("top*.v")):
                if top.name.endswith("_tb.v"):
                    continue
                texto = top.read_text(encoding="utf8")
                puertos = puertos_del_monitor(texto)
                if not puertos:
                    continue
                revisados += 1
                for puerto in ENTRADAS:
                    senal = puertos.get(puerto)
                    if senal is None:
                        continue        # este prototipo no tiene ese puerto
                    conexion = f".{puerto}({senal})"
                    with self.subTest(prototipo=prototipo, top=top.name,
                                      puerto=puerto):
                        self.assertTrue(
                            esta_conducida(texto, senal, conexion),
                            f"{prototipo}/{top.name}: {senal} entra al monitor "
                            f"por .{puerto} y no la conduce nadie")
        # Que la prueba no pase por no haber mirado nada.
        self.assertGreaterEqual(revisados, len(PROTOTIPOS))


# ---------------------------------------------------------------------------
# Anchos de puerto
# ---------------------------------------------------------------------------

_RANGO = r"(?:\[\s*([^\]:]+?)\s*:\s*([^\]]+?)\s*\]\s*)?"
_PUERTO = re.compile(
    r"\b(?:input|output|inout)\s+(?:wire|reg|logic)?\s*" + _RANGO + r"(\w+)")
# Una declaración puede nombrar VARIAS señales: `wire [31:0] a, b;`. Capturar
# sólo la primera dejaba el resto con ancho desconocido, y este test se salta
# lo que no sabe medir -- o sea que `mmio_read_data` no se comprobaba y nadie
# lo habría notado, porque un test que compara menos sigue pasando.
_DECLARACION = re.compile(
    r"^\s*(?:wire|reg)\s+(?:signed\s+)?" + _RANGO + r"([\w\s,]+?)\s*;", re.M)
_INSTANCIA = re.compile(
    r"^\s{2,}([a-z]\w*)\s*(?:#\s*\([^;]*?\))?\s*(\w+)\s*\(", re.M)
_CONEXION = re.compile(r"\.(\w+)\s*\(\s*([^()]*?)\s*\)")

# Palabras que empiezan línea como una instanciación pero no lo son.
_NO_SON_MODULOS = {
    "if", "else", "for", "case", "casez", "endcase", "assign", "always",
    "begin", "end", "wire", "reg", "localparam", "parameter", "initial",
    "generate", "endgenerate", "integer", "genvar", "default",
}


def _constante(expr: str, parametros: dict) -> int | None:
    """Un extremo de rango: literal, parámetro, o `PARAM-1`. Nada más.

    Deliberadamente corto. Lo que no sepa evaluar se salta, y saltarse una
    comparación es aceptable; inventarse un ancho, no.
    """
    expr = expr.strip()
    if re.fullmatch(r"\d+", expr):
        return int(expr)
    if expr in parametros:
        return parametros[expr]
    resta = re.fullmatch(r"(\w+)\s*-\s*(\d+)", expr)
    if resta and resta.group(1) in parametros:
        return parametros[resta.group(1)] - int(resta.group(2))
    return None


def _parametros(texto: str) -> dict:
    valores = {}
    for m in re.finditer(
            r"\b(?:parameter|localparam)\s+(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*([^,;)]+)",
            texto):
        crudo = m.group(2).strip()
        if re.fullmatch(r"\d+", crudo):
            valores[m.group(1)] = int(crudo)
    return valores


def _ancho(alto, bajo, parametros) -> int | None:
    if alto is None:
        return 1                        # sin rango: un bit
    a, b = _constante(alto, parametros), _constante(bajo, parametros)
    return None if a is None or b is None else abs(a - b) + 1


def anchos_de_puerto(ruta: Path) -> dict:
    """{puerto: ancho} de la cabecera de un módulo."""
    texto = ruta.read_text(encoding="utf8", errors="replace")
    cabecera = texto.split(");", 1)[0]
    parametros = _parametros(texto)
    return {m.group(3): _ancho(m.group(1), m.group(2), parametros)
            for m in _PUERTO.finditer(cabecera)}


def desajustes_de_ancho(carpeta: Path) -> tuple[list, int]:
    """(desajustes, comparaciones hechas) en el `top.v` de esa carpeta."""
    return desajustes_de_fichero(carpeta / "top.v", carpeta)


def desajustes_de_fichero(fichero: Path, carpeta: Path) -> tuple[list, int]:
    """Lo mismo, para cualquier fichero que instancie modulos de `carpeta`.

    Se separo de `desajustes_de_ancho` para poder mirar tambien los BANCOS.
    La 21 dejo anotado que este test «solo mira top.v» y que extenderlo era
    trabajo pendiente y probablemente barato; lo era, y hacia falta: la 19
    tenia un banco con la direccion MMIO de CUATRO bits contra un puerto de
    doce, que es el fallo de la 18 con otro numero.
    """
    if not fichero.exists():
        return [], 0
    texto = fichero.read_text(encoding="utf8", errors="replace")
    parametros = _parametros(texto)
    locales = {}
    for m in _DECLARACION.finditer(texto):
        ancho = _ancho(m.group(1), m.group(2), parametros)
        for nombre in m.group(3).split(","):
            nombre = nombre.strip()
            if re.fullmatch(r"\w+", nombre):
                locales[nombre] = ancho

    fallos, comparaciones = [], 0
    for m in _INSTANCIA.finditer(texto):
        modulo = m.group(1)
        if modulo in _NO_SON_MODULOS:
            continue
        fuente = carpeta / f"{modulo}.v"
        if not fuente.exists():
            continue
        puertos = anchos_de_puerto(fuente)

        cursor = _cerrar(texto, m.end())
        for conexion in _CONEXION.finditer(texto[m.end():cursor]):
            puerto, senal = conexion.group(1), conexion.group(2).strip()
            esperado = puertos.get(puerto)
            if esperado is None or not senal:
                continue

            rebanada = re.fullmatch(r"(\w+)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]", senal)
            if rebanada:
                real = abs(int(rebanada.group(2)) - int(rebanada.group(3))) + 1
            elif re.fullmatch(r"\w+", senal):
                real = locales.get(senal)
            else:
                continue                # concatenación, constante, expresión
            if real is None:
                continue                # ancho desconocido: no se inventa

            comparaciones += 1
            if real != esperado:
                linea = texto[:m.end() + conexion.start()].count("\n") + 1
                fallos.append(
                    f"{fichero.name}:{linea}: {modulo}.{puerto} espera "
                    f"{esperado} bit(s) y recibe {senal} de {real}")
    return fallos, comparaciones


class AnchosDePuertoTest(unittest.TestCase):
    """Verilog trunca en silencio; esto no.

    Es el test que habría cazado el fallo de la 18 --doce bits de dirección
    contra cinco-- antes de gastar una síntesis y una placa.
    """

    def test_ninguna_conexion_trunca_en_silencio(self):
        fallos, total = [], 0
        for prototipo in PROTOTIPOS:
            parciales, comparaciones = desajustes_de_ancho(ROOT / prototipo)
            total += comparaciones
            fallos += [f"{prototipo}/{f}" for f in parciales]
        self.assertEqual(
            [], fallos,
            "un puerto recibe una señal de otro ancho. Verilog lo acepta y "
            "trunca o rellena sin avisar:\n  " + "\n  ".join(fallos))
        # Que la prueba no pase por no haber comparado nada. Hoy son ~1440; el
        # umbral es holgado, pero una caída grande significa que el analizador
        # ha dejado de entender los `top.v` y está aprobando por ignorancia.
        #
        # El número importa: la primera versión comparaba 860 porque no
        # entendía `wire [31:0] a, b;` y se saltaba la segunda señal de cada
        # declaración múltiple. Cuatro de cada diez conexiones, en silencio.
        self.assertGreater(total, 1200,
                           f"solo {total} comparaciones: el analizador ha "
                           f"dejado de entender los top.v")

    def test_mira_las_diez_carpetas(self):
        """Sin esto, un cambio de formato en los `top.v` dejaría el test
        comparando cero conexiones y pasando igual."""
        vacias = [p for p in PROTOTIPOS
                  if desajustes_de_ancho(ROOT / p)[1] == 0]
        self.assertEqual([], vacias,
                         f"sin comparar nada en: {vacias}")


#: Desajustes que YA ESTABAN cuando esta comprobación se extendió a los bancos,
#: en carpetas que no eran la que se estaba migrando. Se listan uno a uno, con
#: su motivo, en vez de relajar el criterio: una lista explícita es una deuda;
#: un criterio relajado es un agujero.
#:
#: Cada entrada se borra cuando se arregla, y la regla para quien migre una de
#: estas carpetas es simple: **si tu carpeta aparece aquí, vacíala antes de
#: darla por migrada**.
DEUDA_EN_BANCOS = {
    # Pre-existente y AJENO a MMIO: `wire [7:0] halted, finished, error;`
    # conectado a puertos de 1 bit. `perf_probe_tb.v` es el MISMO banco en las
    # tres carpetas --el de la 18 tiene ocho líneas de comentario menos, y de
    # ahí el desfase de números de línea-- así que arreglarlo es un cambio
    # compartido y no se mezcla con una migración de direcciones.
    #
    # Ojo con la palabra «idéntica», que es la que había aquí y no es cierta:
    # invita a copiar el fichero de una carpeta a otra, y esas ocho líneas son
    # justo las que explican que este banco monta `sdram_system_adapter` a
    # propósito y NO debe migrarse nunca.
    "18.fpga-cpu-hdmi-bl8/perf_probe_tb.v:179",
    "18.fpga-cpu-hdmi-bl8/perf_probe_tb.v:180",
    "18.fpga-cpu-hdmi-bl8/perf_probe_tb.v:195",
    "19.fpga-cpu-hdmi-ls/perf_probe_tb.v:187",
    "19.fpga-cpu-hdmi-ls/perf_probe_tb.v:188",
    "19.fpga-cpu-hdmi-ls/perf_probe_tb.v:203",
    "21.fpga-cpu-hdmi-alu/perf_probe_tb.v:187",
    "21.fpga-cpu-hdmi-alu/perf_probe_tb.v:188",
    "21.fpga-cpu-hdmi-alu/perf_probe_tb.v:203",

    # La 18 tenía dos más, en `video_fullframe_tb.v`, de cuando estaba en v1.
    # Se arreglaron al migrarla, así que NO están en esta lista: era deuda de
    # verdad y no una excepción. Las tres de `perf_probe_tb` se quedan porque
    # son de otra clase.

    # La 21 tenía cuatro más, de dirección MMIO, que su migración no ensanchó
    # (`mon_mmio_addr` de 5 bits, `mmio_addr` de 4, y una rebanada implícita
    # hacia `video_registers`). Se arreglaron al extender este test, así que
    # NO están en esta lista: era deuda de verdad, no una excepción.
}


class AnchosEnBancosTest(unittest.TestCase):
    """Lo mismo que `AnchosDePuertoTest`, pero en los bancos.

    Hace falta porque el otro **sólo mira `top.v`**, y el fallo de la 18 vive
    igual de bien dentro de un banco: la 19 tenía `wire [3:0] mmio_mask,
    mmio_addr;` --la máscara sí es de cuatro bits, la dirección heredó la
    anchura por compartir declaración-- contra un puerto de doce.

    Un banco con la dirección truncada no da error: da un banco que PASA
    probando otra cosa. `video_registers` selecciona su registro con
    `address[7:2]`, así que con cinco bits los registros por encima de +0x1C
    aliasan sobre los de abajo.
    """

    def test_ningun_banco_trunca_en_silencio(self):
        fallos, total = [], 0
        for prototipo in PROTOTIPOS:
            carpeta = ROOT / prototipo
            for banco in sorted(carpeta.glob("*_tb.v")):
                parciales, comparaciones = desajustes_de_fichero(
                    banco, carpeta)
                total += comparaciones
                for f in parciales:
                    # "fichero.v:LINEA: resto" -> clave "carpeta/fichero.v:LINEA"
                    clave = f"{prototipo}/{f.split(':')[0]}:{f.split(':')[1]}"
                    if clave not in DEUDA_EN_BANCOS:
                        fallos.append(f"{prototipo}/{f}")
        self.assertEqual(
            [], fallos,
            "un puerto de un banco recibe una señal de otro ancho. Verilog "
            "trunca sin avisar y el banco pasa probando otra cosa:\n  "
            + "\n  ".join(fallos))
        # La misma guarda que arriba: un analizador que deja de entender los
        # bancos aprobaría por ignorancia. Hoy son ~4680.
        self.assertGreater(total, 4000,
                           f"solo {total} comparaciones en bancos: el "
                           f"analizador ha dejado de entenderlos")

    def test_el_top_no_estrecha_el_bitmap_de_video(self):
        """`top.v` no puede declarar MENOS registros de vídeo de los que su
        `mmio_decoder.v` trae por defecto.

        Nace de un fallo real y caro de la 21, ya migrada: su `top.v` pasaba
        `VIDEO_REGISTERS(64'h7f)` --los SIETE registros de v1-- pisando el
        `64'h3ff` de v2. En el bitstream, `HALT_AT`, `HALT_TARGET` y
        `VIDEO_TX` contestaban **error de acceso** aunque `video_registers.v`
        los implementa.

        No lo vio nadie, y no por descuido: su `cpu_mmio_error_tb` instancia
        el decodificador con `0x3ff` por su cuenta, así que probaba el
        decodificador y no el diseño. Y ningún banco instancia `top`, que es
        la misma razón por la que existe el resto de este fichero.

        El valor de v1 es lo que lo hace invisible: `0x7f` es un bitmap
        perfectamente válido, así que nada tenía de qué quejarse.
        """
        bitmap = re.compile(r"\.VIDEO_REGISTERS\(\s*64'h([0-9a-fA-F_]+)\s*\)")
        registro = re.compile(
            r"localparam\s*\[\d+:\d+\]\s*REG_\w+\s*=\s*\d+'d(\d+)\s*;")
        fallos, revisados = [], 0
        for prototipo in PROTOTIPOS:
            carpeta = ROOT / prototipo
            top, dev = carpeta / "top.v", carpeta / "video_registers.v"
            if not top.exists() or not dev.exists():
                continue
            # La gemela NO es el valor por defecto del decodificador --que es
            # el del contrato, y una carpeta puede implementar menos-- sino lo
            # que ESTE `video_registers.v` implementa de verdad. La 16 declara
            # 0x4f con toda la razón: sólo tiene cinco registros, en los
            # índices 0,1,2,3 y 6.
            indices = [int(x) for x in
                       registro.findall(dev.read_text(encoding="utf8",
                                                      errors="replace"))]
            n = bitmap.search(top.read_text(encoding="utf8", errors="replace"))
            if not indices or not n:
                continue
            revisados += 1
            esperado = sum(1 << i for i in indices)
            real = int(n.group(1).replace("_", ""), 16)
            if real != esperado:
                faltan = [i for i in indices if not (real >> i) & 1]
                fallos.append(
                    f"{prototipo}/top.v pasa VIDEO_REGISTERS=0x{real:x} pero "
                    f"su video_registers.v implementa 0x{esperado:x} "
                    f"(faltan los índices {faltan}); esos registros darán "
                    f"error de acceso en la placa aunque el RTL los tenga")
        self.assertEqual([], fallos, "\n  ".join([""] + fallos))
        self.assertGreater(revisados, 3,
                           "no se ha comprobado casi ningún top.v; el "
                           "analizador ha dejado de entenderlos")

    def test_la_deuda_no_crece_ni_se_queda_rancia(self):
        """Una lista de excepciones sin mantenimiento se convierte en el
        agujero que venía a evitar. Esto exige que cada entrada siga siendo un
        desajuste de verdad: si alguien lo arregla y no borra la línea, salta y
        obliga a borrarla."""
        vivos = set()
        for prototipo in PROTOTIPOS:
            carpeta = ROOT / prototipo
            for banco in sorted(carpeta.glob("*_tb.v")):
                for f in desajustes_de_fichero(banco, carpeta)[0]:
                    partes = f.split(":")
                    vivos.add(f"{prototipo}/{partes[0]}:{partes[1]}")
        rancias = sorted(DEUDA_EN_BANCOS - vivos)
        self.assertEqual(
            [], rancias,
            "estas entradas de DEUDA_EN_BANCOS ya no corresponden a ningún "
            "desajuste. Bórralas de la lista:\n  " + "\n  ".join(rancias))


if __name__ == "__main__":
    unittest.main()
