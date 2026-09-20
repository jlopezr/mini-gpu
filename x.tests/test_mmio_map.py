"""La fuente única de constantes MMIO y lo que se genera de ella.

`1.isa/mmio.md` §20 pide un include Verilog tonto como fuente maestra, y avisa
de lo que hay que resolver **antes** de construirlo:

> un fichero generado se desincroniza en silencio si alguien toca el RTL y no
> regenera, mientras que un test que compara falla a gritos

Esto es ese test. Vigila tres cosas distintas, y conviene no confundirlas
porque ninguna cubre a las otras:

1. **Sincronía** — lo que hay en disco es lo que sale del generador hoy.
   No dice nada sobre si el mapa es correcto.
2. **Conformidad** — las direcciones del mapa son las que dice `mmio.md`.
   Éste es el que caza un `mmio_map.vh` mal editado, que la sincronía deja
   pasar tan contenta porque regenera igual de bien un mapa equivocado.
3. **Solidez del generador** — que se niegue a producir algo inválido en vez
   de producirlo en silencio.

La tercera existe por experiencia propia: la primera versión del generador
adivinaba a qué bloque pertenece cada offset por el prefijo del nombre, y
colgó los descriptores de warp y todo SIMT DEBUG de `MMIO_GPU_BASE` —se
llamaban `MMIO_GPU_WARP_*` y la base es `MMIO_GPU_WARPS_BASE`, con S—. El
resultado fue `GPU_WARP_PC` en la misma dirección que `GPU_ID`. Nada falló:
el `.inc` se generó, el ensamblador lo tragó y el programa habría escrito en
el registro equivocado.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "1.isa") not in sys.path:
    sys.path.insert(0, str(ROOT / "1.isa"))

from tools.generate_mmio import (  # noqa: E402
    MmioMapError, SOURCE, SOURCE_V1, base_de, desincronizados, generar,
    parse_map, render_inc,
)


class SincroniaTest(unittest.TestCase):
    """Lo generado está al día. Es el test que `mmio.md` §20 exige."""

    def test_lo_generado_esta_al_dia(self):
        fuera = desincronizados()
        self.assertEqual(
            [], fuera,
            "hay ficheros generados desincronizados de 1.isa/mmio_map.vh. "
            "Ejecuta ./tools/generate-mmio y vuelve a commitear:\n  "
            + "\n  ".join(str(p) for p in fuera))

    def test_los_destinos_se_generan(self):
        """Si alguien añade una salida y olvida el test, esto lo dice. Y lo
        dijo dos veces, las dos sin que nadie lo provocara: al añadir el mapa
        v1 durante la migración de la 21, y al RESUCITARLO para la 19 después
        de haberlo borrado. Es el único test de este fichero que ha saltado
        por su cuenta."""
        destinos = {p.name for p in generar()}
        self.assertEqual(
            {"mmio.inc", "mmio_map.py",
             "mmio_v1.inc", "mmio_map_v1.py"}, destinos)


class ConformidadTest(unittest.TestCase):
    """Las direcciones son las del contrato.

    Los números están escritos a mano ADREDE, copiados de `mmio.md`. Derivarlos
    del mismo sitio que el generador convertiría el test en una tautología: un
    mapa mal editado pasaría, que es justo el fallo que importa. La duplicación
    aquí es el mecanismo, no un descuido.
    """

    @classmethod
    def setUpClass(cls):
        cls.mapa = parse_map(SOURCE.read_text(encoding="utf-8"))

    def test_bases_de_bloque(self):
        """mmio.md §2."""
        esperado = {
            "MMIO_SYSTEM_BASE": 0x80000000,
            "MMIO_FABRIC_BASE": 0x80010000,
            "MMIO_SDRAM_BASE": 0x80020000,
            "MMIO_SERIAL_BASE": 0x80100000,
            "MMIO_VIDEO_BASE": 0x80200000,
            "MMIO_TIMER_BASE": 0x80300000,
            "MMIO_INTC_BASE": 0x80400000,
            "MMIO_DMA_BASE": 0x80500000,
            "MMIO_CPU_BASE": 0x81000000,
            "MMIO_CPU_PERF_BASE": 0x81010000,
            "MMIO_CPU_DEBUG_BASE": 0x81020000,
            "MMIO_GPU_BASE": 0x82000000,
            "MMIO_GPU_WARPS_BASE": 0x82010000,
            "MMIO_GPU_SIMT_BASE": 0x82020000,
            "MMIO_GPU_PERF_BASE": 0x82030000,
        }
        for nombre, valor in esperado.items():
            with self.subTest(nombre):
                self.assertEqual(valor, self.mapa[nombre])

    def test_todas_las_bases_alineadas_a_64_kib(self):
        """§2.1: es lo que permite cargar cualquiera con un solo `MOVHI`."""
        for nombre, valor in self.mapa.items():
            if nombre.endswith("_BASE") and nombre != "MMIO_MEM_BASE":
                with self.subTest(nombre):
                    self.assertEqual(0, valor & 0xFFFF)

    def test_registros_de_video(self):
        """§9. `CTRL` en +0x00 y `FRAME_COUNT` con registro propio son dos de
        los cambios de v2 respecto al mapa viejo."""
        esperado = {
            "MMIO_VIDEO_CTRL_OFF": 0x00,
            "MMIO_VIDEO_FB_FRONT_OFF": 0x04,
            "MMIO_VIDEO_FB_BACK_OFF": 0x08,
            "MMIO_VIDEO_SWAP_OFF": 0x0C,
            "MMIO_VIDEO_STATUS_OFF": 0x10,
            "MMIO_VIDEO_FRAME_COUNT_OFF": 0x14,
            "MMIO_VIDEO_SWAP_COUNT_OFF": 0x18,
            "MMIO_VIDEO_HALT_AT_OFF": 0x1C,
            "MMIO_VIDEO_HALT_TARGET_OFF": 0x20,
            "MMIO_VIDEO_TX_OFF": 0x24,
        }
        for nombre, valor in esperado.items():
            with self.subTest(nombre):
                self.assertEqual(valor, self.mapa[nombre])

    def test_registros_de_system(self):
        """§5: siete palabras, no cuatro."""
        esperado = {
            "MMIO_SYSTEM_MAGIC_OFF": 0x00,
            "MMIO_SYSTEM_MMIO_VERSION_OFF": 0x04,
            "MMIO_SYSTEM_SYSTEM_ID_OFF": 0x08,
            "MMIO_SYSTEM_DEVICES_OFF": 0x0C,
            "MMIO_SYSTEM_MEM_BASE_OFF": 0x10,
            "MMIO_SYSTEM_MEM_SIZE_OFF": 0x14,
            "MMIO_SYSTEM_MONITOR_VERSION_OFF": 0x18,
        }
        for nombre, valor in esperado.items():
            with self.subTest(nombre):
                self.assertEqual(valor, self.mapa[nombre])

    def test_magic(self):
        """§5.1. Se copia mal con una facilidad notable."""
        self.assertEqual(0x4D474155, self.mapa["MMIO_MAGIC_VALUE"])

    def test_serial(self):
        """§8."""
        self.assertEqual(0x00, self.mapa["MMIO_SERIAL_DATA_OFF"])
        self.assertEqual(0x04, self.mapa["MMIO_SERIAL_STATUS_OFF"])
        self.assertEqual(0x08, self.mapa["MMIO_SERIAL_PEEK_OFF"])

    def test_disposicion_de_contadores(self):
        """§12.6: el array arranca en 0 y el control va DETRÁS de su extensión
        máxima, no pegado al último contador."""
        self.assertEqual(0x00, self.mapa["MMIO_PERF_CYCLES_OFF"])
        self.assertEqual(64, self.mapa["MMIO_PERF_MAX_COUNTERS"])
        self.assertEqual(0x100, self.mapa["MMIO_PERF_CTRL_OFF"])
        self.assertEqual(0x104, self.mapa["MMIO_PERF_OVF0_OFF"])
        self.assertEqual(0x108, self.mapa["MMIO_PERF_OVF1_OFF"])
        # El control cae justo detrás de 64 ranuras de 4 bytes. Si alguien
        # sube MAX_COUNTERS sin mover el control, se solapan.
        self.assertEqual(self.mapa["MMIO_PERF_MAX_COUNTERS"] * 4,
                         self.mapa["MMIO_PERF_CTRL_OFF"])

    def test_bits_de_devices_congelados(self):
        """§5.4: una asignación de bit nunca cambia de significado."""
        esperado = {
            "MMIO_DEV_SYSTEM_BIT": 0, "MMIO_DEV_FABRIC_BIT": 1,
            "MMIO_DEV_SDRAM_BIT": 2, "MMIO_DEV_EBR_BIT": 3,
            "MMIO_DEV_SERIAL_BIT": 4, "MMIO_DEV_VIDEO_BIT": 5,
            "MMIO_DEV_TIMER_BIT": 6, "MMIO_DEV_INTC_BIT": 7,
            "MMIO_DEV_DMA_BIT": 8, "MMIO_DEV_CPU_BIT": 9,
            "MMIO_DEV_GPU_BIT": 10,
        }
        for nombre, valor in esperado.items():
            with self.subTest(nombre):
                self.assertEqual(valor, self.mapa[nombre])

    def test_ningun_bloque_se_solapa(self):
        """Todos los bloques miden `MMIO_BLOCK_SIZE`, así que dos bases a menos
        de esa distancia serían el mismo bloque con dos nombres."""
        tam = self.mapa["MMIO_BLOCK_SIZE"]
        bases = sorted(
            (v, k) for k, v in self.mapa.items()
            if k.endswith("_BASE") and k != "MMIO_MEM_BASE")
        for (v1, n1), (v2, n2) in zip(bases, bases[1:]):
            with self.subTest(f"{n1} vs {n2}"):
                self.assertGreaterEqual(v2 - v1, tam, f"{n1} y {n2} se pisan")


class BloqueDeCadaOffsetTest(unittest.TestCase):
    """`base_de` asigna cada `_OFF` a su bloque. Es donde estuvo el fallo."""

    @classmethod
    def setUpClass(cls):
        cls.mapa = parse_map(SOURCE.read_text(encoding="utf-8"))

    def test_los_descriptores_de_warp_van_a_warps_no_a_gpu(self):
        """El fallo concreto que hubo, fijado para que no vuelva."""
        self.assertEqual("MMIO_GPU_WARPS_BASE",
                         base_de("MMIO_GPU_WARPS_PC_OFF", self.mapa))

    def test_simt_debug_va_a_su_bloque(self):
        self.assertEqual("MMIO_GPU_SIMT_BASE",
                         base_de("MMIO_GPU_SIMT_CONTEXT_OFF", self.mapa))

    def test_warp_start_si_pertenece_a_gpu_core(self):
        """El contraste: éste SÍ va en GPU CORE (§14.1), y el nombre parecido
        es justo lo que hacía difícil ver el fallo del otro."""
        self.assertEqual("MMIO_GPU_BASE",
                         base_de("MMIO_GPU_WARP_START_OFF", self.mapa))

    def test_los_offsets_plantilla_no_tienen_bloque(self):
        """`MMIO_PERF_*` vale para CPU PERF y para GPU PERF, así que no tiene
        una dirección absoluta única y no se le inventa una."""
        self.assertIsNone(base_de("MMIO_PERF_CYCLES_OFF", self.mapa))


class GeneradorEstrictoTest(unittest.TestCase):
    """Lo que el generador tiene que RECHAZAR.

    Una línea que el parser no entiende y se salta es una constante que
    desaparece del fichero generado sin que nadie se entere.
    """

    def test_rechaza_una_expresion(self):
        """La regla 1 de `mmio_map.vh`. Con una expresión dentro, leerlo pide
        un parser de Verilog y la fuente única deja de ser única."""
        with self.assertRaises(MmioMapError) as ctx:
            parse_map("`define A 32'h8000_0000 + 4\n")
        self.assertIn("sin expresiones", str(ctx.exception))

    def test_rechaza_una_referencia_a_otra_constante(self):
        with self.assertRaises(MmioMapError):
            parse_map("`define A 32'h8000_0000\n`define B `A\n")

    def test_rechaza_una_linea_que_no_es_define(self):
        with self.assertRaises(MmioMapError) as ctx:
            parse_map("`ifdef ALGO\n`define A 32'h0000_0000\n`endif\n")
        self.assertIn("solo se admiten lineas", str(ctx.exception))

    def test_rechaza_duplicados(self):
        with self.assertRaises(MmioMapError) as ctx:
            parse_map("`define A 32'h0000_0000\n`define A 32'h0000_0004\n")
        self.assertIn("duplicada", str(ctx.exception))

    def test_rechaza_un_fichero_vacio(self):
        with self.assertRaises(MmioMapError):
            parse_map("// solo comentarios\n")

    def test_admite_comentarios_y_lineas_en_blanco(self):
        mapa = parse_map(
            "// cabecera\n\n`define MMIO_A_BASE 32'h8000_0000  // al final\n")
        self.assertEqual({"MMIO_A_BASE": 0x80000000}, mapa)

    def test_caza_dos_registros_en_la_misma_direccion(self):
        """La red de seguridad de `base_de`, reproduciendo el fallo original:
        un `_OFF` cuyo nombre encaja con el `_BASE` equivocado."""
        mapa = parse_map(
            "`define MMIO_GPU_BASE 32'h8200_0000\n"
            "`define MMIO_GPU_ID_OFF 32'h0000_0000\n"
            "`define MMIO_GPU_WARP_PC_OFF 32'h0000_0000\n")
        with self.assertRaises(MmioMapError) as ctx:
            render_inc(mapa)
        self.assertIn("0x82000000", str(ctx.exception))
        self.assertIn("no encaja", str(ctx.exception))


class RegionesDelMonitorTest(unittest.TestCase):
    """`MONITOR_REGIONS` de la 21 dice lo mismo que el mapa generado.

    Van escritas a mano en `monitor.py` por una razón concreta:
    `tools/prototype_report.py` las lee del TEXTO del fichero, sin importar el
    módulo, así que una expresión las deja invisibles. Escribirlas a mano es
    obligatorio; dejarlas sin contrastar, no.
    """

    def test_las_regiones_son_las_del_mapa(self):
        sys.path.insert(0, str(ROOT / "21.fpga-cpu-hdmi-alu"))
        try:
            import monitor  # noqa: PLC0415
        finally:
            sys.path.pop(0)
        from tools import mmio_map as mapa  # noqa: PLC0415

        esperado = {
            (base, base + mapa.MMIO_BLOCK_SIZE)
            for base in (mapa.MMIO_SYSTEM_BASE, mapa.MMIO_SERIAL_BASE,
                         mapa.MMIO_VIDEO_BASE, mapa.MMIO_CPU_PERF_BASE)
        }
        self.assertEqual(esperado, set(monitor.MONITOR_REGIONS))


class NingunProgramaLlevaDireccionesCableadasTest(unittest.TestCase):
    """Definición de hecho: ningún `.asm` lleva una dirección MMIO a mano.

    Se mira el fuente, no el binario, porque lo que se quiere impedir es que
    alguien escriba el número — no que el número exista. Un `MOVHI Rn, 0x8000`
    nuevo en cualquiera de estas carpetas tiene que saltar aquí y no en la
    placa tres semanas después.
    """

    # `cases-shared` y `20.forth` faltaban en la primera versión, y los dos
    # tenían una dirección cableada. No se descubrió aquí sino corriendo el
    # simulador, que es tarde: el sentido de esta guarda es que un `.asm`
    # nuevo salte en un test barato y no tres capas más abajo.
    #
    # La lección es de alcance, no de patrón: los programas de este repo NO
    # viven todos bajo `x.tests/cases`. Al migrar la siguiente carpeta,
    # empieza por listar dónde hay `.asm`.
    # La 19 faltaba, y por eso sus doce programas siguieron en v1 sin que nadie
    # se enterara: la guarda existia, la carpeta no estaba dentro. Una lista de
    # carpetas escrita a mano vigila lo que le han dicho, no lo que hay.
    CARPETAS = (
        ROOT / "x.tests" / "cases",
        ROOT / "x.tests" / "cases-shared",
        ROOT / "20.forth",
        ROOT / "18.fpga-cpu-hdmi-bl8" / "examples",
        ROOT / "19.fpga-cpu-hdmi-ls" / "examples",
        ROOT / "21.fpga-cpu-hdmi-alu" / "examples",
    )

    # `MOVHI Rn, 0x8000` carga la mitad alta de 0x80000000. Buscar eso a secas
    # NO vale, y es un error que este test cometió antes de existir: en
    # `shift-amount`, `mulhi-signed`, `remainder-signs` y `compare` ese mismo
    # literal es INT_MIN, un operando de la ALU que no es ninguna dirección.
    # Migrarlos habría roto cuatro casos buenos.
    #
    # Lo que distingue una cosa de la otra no es el valor, es el uso: es una
    # dirección si el registro se DESREFERENCIA después. INT_MIN se suma, se
    # desplaza y se compara; una base se pone debajo de un LOAD o un STORE.
    CARGA = re.compile(r"^[ \t]*MOVHI\s+(R\d+)\s*,\s*0x8000\b.*$",
                       re.IGNORECASE | re.MULTILINE)

    @staticmethod
    def _se_desreferencia(texto: str, registro: str) -> bool:
        return re.search(
            rf"^\s*(?:LOAD|STORE)[A-Z]*\s+R\d+\s*,\s*{registro}\s*,",
            texto, re.IGNORECASE | re.MULTILINE) is not None

    def test_ningun_asm_carga_una_base_mmio_a_mano(self):
        culpables = []
        for carpeta in self.CARPETAS:
            for fuente in sorted(carpeta.rglob("*.asm")):
                texto = fuente.read_text(encoding="utf-8", errors="replace")
                for match in self.CARGA.finditer(texto):
                    if not self._se_desreferencia(texto, match.group(1)):
                        continue        # es un operando, no una dirección
                    linea = texto[:match.start()].count("\n") + 1
                    culpables.append(
                        f"{fuente.relative_to(ROOT)}:{linea}: "
                        f"{match.group(0).strip()}")
        self.assertEqual(
            [], culpables,
            "una dirección MMIO cableada. Usa el mapa:\n  "
            '.include "mmio.inc"\n      LI R20, MMIO_VIDEO_BASE\n\nEncontradas:\n  "'
            + "\n  ".join(culpables))

    def test_int_min_no_se_confunde_con_una_direccion(self):
        """El control de la regla anterior, en los dos sentidos. Sin esto, el
        test se podría «arreglar» excluyendo a mano los cuatro casos de ALU, y
        el siguiente que usara INT_MIN volvería a saltar."""
        operando = "MOVHI R13, 0x8000\nADD R1, R13, R2\n"
        direccion = "MOVHI R13, 0x8000\nLOAD R1, R13, 4\n"
        self.assertFalse(self._se_desreferencia(operando, "R13"))
        self.assertTrue(self._se_desreferencia(direccion, "R13"))

    def test_los_casos_de_alu_siguen_usando_int_min(self):
        """Que los cuatro sigan ahí sin tocar. Si alguien los «migrara» por
        error, el valor dejaría de ser INT_MIN y el caso probaría otra cosa."""
        for ruta in ("cases/alu/shift-amount/program.asm",
                     "cases/extensions/alu-extended/mulhi-signed/program.asm",
                     "cases/extensions/compare/signed-unsigned/program.asm"):
            with self.subTest(ruta):
                texto = (ROOT / "x.tests" / ruta).read_text(encoding="utf-8")
                self.assertRegex(texto, r"MOVHI\s+R\d+,\s*0x8000")


class EnsamblaDeVerdadTest(unittest.TestCase):
    """El `.inc` no sólo se genera: el ensamblador lo resuelve y da los
    números del contrato. Sin esto, un `.inc` sintácticamente válido pero
    inútil pasaría los otros tests."""

    def test_un_programa_usa_las_constantes(self):
        from miniisa_asm import assemble

        palabras = assemble(
            '.include "mmio.inc"\n'
            ".word MMIO_VIDEO_FB_FRONT_ADDR\n"
            ".word MMIO_SERIAL_DATA_ADDR\n"
            ".word MMIO_GPU_SIMT_CONTEXT_ADDR\n"
            ".word MMIO_MAGIC_VALUE\n",
            include_dirs=(ROOT / "x.tests" / "inc",))
        self.assertEqual(
            [0x80200004, 0x80100000, 0x82020000, 0x4D474155], palabras)

    def test_li_carga_una_base(self):
        from miniisa_asm import assemble

        palabras = assemble(
            '.include "mmio.inc"\nLI R2, MMIO_VIDEO_BASE\n',
            include_dirs=(ROOT / "x.tests" / "inc",))
        self.assertEqual(2, len(palabras))
        self.assertEqual(0x8020, palabras[0] & 0xFFFF)
        self.assertEqual(0x0000, palabras[1] & 0xFFFF)

    def test_el_inc_es_idempotente(self):
        """Lleva `.once`, así que incluirlo dos veces --que pasará en cuanto
        un `.inc` de biblioteca lo incluya también-- no duplica constantes."""
        from miniisa_asm import assemble

        palabras = assemble(
            '.include "mmio.inc"\n.include "mmio.inc"\n'
            ".word MMIO_VIDEO_BASE\n",
            include_dirs=(ROOT / "x.tests" / "inc",))
        self.assertEqual([0x80200000], palabras)


class MapaV1Test(unittest.TestCase):
    """El andamio de transición: `1.isa/mmio_map_v1.vh`.

    Existe para que los `.asm` de una carpeta pasen a símbolos SIN mover
    ninguna dirección, y que migrarla sea después cambiar la línea del
    `.include`. Todo ese plan se apoya en un invariante que hay que comprobar,
    porque si falla no se nota al ensamblar sino en la placa.

    Esta clase se borra con el mapa, cuando migre la última carpeta.
    """

    def test_los_nombres_de_v1_existen_todos_en_v2(self):
        """EL invariante. Si un nombre de v1 no está en v2, cambiar el
        `.include` deja un símbolo sin definir... y eso, al menos, es ruidoso.

        Lo que de verdad protege es lo contrario de lo que parece: garantiza
        que la migración de un `.asm` sea UNA línea. En cuanto un nombre no
        existe en los dos lados, migrar ese fichero deja de ser mecánico y hay
        que mirarlo, que es exactamente cuando la gente se equivoca."""
        nombres = re.compile(r"`define\s+([A-Z][A-Z0-9_]*)")
        v2 = set(nombres.findall(SOURCE.read_text(encoding="utf-8")))
        v1 = set(nombres.findall(SOURCE_V1.read_text(encoding="utf-8")))
        self.assertEqual(
            set(), v1 - v2,
            "hay constantes en el mapa v1 que no existen en v2, así que "
            "cambiar el `.include` de un .asm no basta para migrarlo")

    def test_los_valores_son_los_del_rtl_sin_migrar(self):
        """Los números, copiados A MANO del RTL de la 19.

        La duplicación es el mecanismo, igual que en `ConformidadTest`:
        derivarlos del generador haría que este test pasara siempre. Fuentes:
        `mmio_decoder.v` (device = address[11:8] sobre 0x80000) y los
        `localparam REG_*` de cada dispositivo."""
        from tools import mmio_map_v1 as v1  # noqa: PLC0415

        # Ranuras de 256 bytes en una página de 4 KiB: DEV_VIDEO=0,
        # DEV_SERIAL=2, DEV_PERF=3, DEV_SYSID=15.
        self.assertEqual(0x80000000, v1.MMIO_VIDEO_BASE)
        self.assertEqual(0x80000200, v1.MMIO_SERIAL_BASE)
        self.assertEqual(0x80000300, v1.MMIO_CPU_PERF_BASE)
        self.assertEqual(0x80000F00, v1.MMIO_SYSTEM_BASE)

        # video_registers.v: CTRL es el 6 porque se añadió el último. En v2
        # está en +0x00 y empuja a todos los demás.
        self.assertEqual(0x00, v1.MMIO_VIDEO_FB_FRONT_OFF)
        self.assertEqual(0x04, v1.MMIO_VIDEO_FB_BACK_OFF)
        self.assertEqual(0x08, v1.MMIO_VIDEO_SWAP_OFF)
        self.assertEqual(0x0C, v1.MMIO_VIDEO_STATUS_OFF)
        self.assertEqual(0x10, v1.MMIO_VIDEO_SWAP_COUNT_OFF)
        self.assertEqual(0x14, v1.MMIO_VIDEO_HALT_AT_OFF)
        self.assertEqual(0x18, v1.MMIO_VIDEO_CTRL_OFF)

        # serial_port.v: los tres coinciden con v2; sólo se mueve la base.
        self.assertEqual(0x00, v1.MMIO_SERIAL_DATA_OFF)
        self.assertEqual(0x04, v1.MMIO_SERIAL_STATUS_OFF)
        self.assertEqual(0x08, v1.MMIO_SERIAL_PEEK_OFF)

    def test_video_se_mueve_entero_al_pasar_a_v2(self):
        """Lo que hace peligrosa la migración de esta carpeta, fijado.

        No es que la base cambie --eso da error de decodificación, que es
        ruidoso--: es que los CUATRO registros que usan los programas de la 19
        cambian de offset. Un `.asm` a medio migrar no falla, escribe en el
        registro de al lado."""
        from tools import mmio_map as v2  # noqa: PLC0415
        from tools import mmio_map_v1 as v1  # noqa: PLC0415

        for nombre in ("FB_FRONT", "FB_BACK", "SWAP", "CTRL"):
            self.assertNotEqual(
                getattr(v1, f"MMIO_VIDEO_{nombre}_OFF"),
                getattr(v2, f"MMIO_VIDEO_{nombre}_OFF"),
                f"{nombre} tiene el mismo offset en v1 y v2; si esto pasa a "
                "ser cierto, revisa este test antes de creértelo")

    def test_incluir_los_dos_mapas_a_la_vez_es_error(self):
        """Un programa a medio migrar NO ensambla.

        Los dos `.inc` definen los mismos nombres, así que el ensamblador los
        rechaza por constante duplicada. Es la red que impide dejarse un
        `.include` viejo al lado del nuevo."""
        from miniisa_asm import assemble

        with self.assertRaises(Exception) as caso:
            assemble(
                '.include "mmio_v1.inc"\n.include "mmio.inc"\n'
                ".word MMIO_VIDEO_BASE\n",
                include_dirs=(ROOT / "x.tests" / "inc",))
        # Salta en la PRIMERA constante común, no en una concreta, y el
        # mensaje nombra los dos ficheros y las dos líneas.
        mensaje = str(caso.exception)
        self.assertIn("constante duplicada", mensaje)
        self.assertIn("mmio_v1.inc", mensaje)

    def test_ensambla_de_verdad_contra_el_mapa_de_hoy(self):
        """Y da las direcciones de HOY, no las de v2."""
        from miniisa_asm import assemble

        palabras = assemble(
            '.include "mmio_v1.inc"\n'
            ".word MMIO_VIDEO_FB_FRONT_ADDR\n"
            ".word MMIO_VIDEO_CTRL_ADDR\n"
            ".word MMIO_SERIAL_DATA_ADDR\n",
            include_dirs=(ROOT / "x.tests" / "inc",))
        self.assertEqual([0x80000000, 0x80000018, 0x80000200], palabras)


if __name__ == "__main__":
    unittest.main()
