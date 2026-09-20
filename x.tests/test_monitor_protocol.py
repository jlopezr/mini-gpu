"""El protocolo vive una vez, y cada carpeta declara lo que su hardware tiene.

Los diez `monitor.py` con juego de comandos tenían 20 de los 21 métodos de
`MonitorClient` byte a byte idénticos; el único que difería, `read_word`,
difería sólo en el docstring. Ahora el protocolo está en
`tools/monitor_protocol.py` y cada carpeta compone su cliente con los mixins
que le corresponden.

Lo que estos tests protegen es la propiedad que hace que eso valga la pena:
**que un cliente sepa mandar exactamente los comandos que su hardware
atiende**. Ni menos --un comando que el PC deja de saber mandar no se nota
hasta tener la placa delante-- ni más, que es el que de verdad engaña: un
método heredado de balde contra hardware que no lo implementa falla con «The
FPGA rejected the command», que suena a avería y es una capacidad que nunca
existió.

El caso que lo demostró durante la propia refactorización: `configure_warps`
valida el JSON contra un modelo del simulador antes de tocar la placa, y la 12
usa 128 KiB --su EBR-- mientras las otras tres usan 32 MiB. Dejar el valor
compartido hacía pasar un `pc` de 0x20000 que en esa placa no existe. Lo cazó
`test_monitor.py` de la 12; `MODEL_MEMORY_SIZE` es ahora de cada carpeta.
"""

import ast
import importlib
import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Las carpetas con juego de comandos. 5, 8 y 9 quedan fuera: no son ni CPU ni
# GPU, su monitor es otra cosa.
PROTOTIPOS = ("6.fpga-cpu", "10.fpga-cpu-ram", "12.fpga-gpu", "14.fpga-gpu-ram",
              "16.fpga-cpu-hdmi", "17.fpga-gpu-ram-v2", "18.fpga-cpu-hdmi-bl8",
              "19.fpga-cpu-hdmi-ls", "21.fpga-cpu-hdmi-alu", "22.fpga-gpu-bl8")

# Comando opcional -> qué tiene que haber en el RTL de la carpeta para que su
# cliente pueda mandarlo. Igual que `capabilities.json`, la fuente de verdad es
# el hardware y no una lista escrita a mano.
OPCIONALES = {
    "send_bytes": "serial_port.v",
    "recv_bytes": "serial_port.v",
    "send_all": "serial_port.v",
    "get_cycles": "cpu_perf_counters.v",
    "get_instructions": "cpu_perf_counters.v",
}


def cargar(prototipo: str):
    for nombre in [m for m in sys.modules if m == "monitor"]:
        del sys.modules[nombre]
    sys.path.insert(0, str(ROOT / prototipo))
    try:
        return importlib.import_module("monitor")
    finally:
        sys.path.pop(0)


class IdentificacionHostTest(unittest.TestCase):
    def test_cero_rechazo_y_magic_son_distintos(self):
        from tools.monitor_protocol import MonitorClient
        from unittest.mock import Mock
        def client(response):
            connection = Mock()
            data = bytearray(response)
            def read(count):
                out = bytes(data[:count])
                del data[:count]
                return out
            connection.read.side_effect = read
            return MonitorClient(connection)
        self.assertEqual(client(b"\x92\x16\x00\x47\x4d").probe_sys_id(), 0x4D470016)
        self.assertEqual(client(b"\x92\x00\x00\x00\x00").probe_sys_id(), 0)
        self.assertIsNone(client(b"\xff").probe_sys_id())
        from tools.monitor_protocol import MonitorError
        for response in (b"", b"\x92\x00", b"\x91", b"\x92\x01\x00\x00\x00"):
            with self.subTest(response=response), self.assertRaises(MonitorError):
                client(response).probe_sys_id()


class ProtocoloCompartidoTest(unittest.TestCase):
    def test_ningun_monitor_reimplementa_el_protocolo(self):
        """Si alguien vuelve a pegar el cliente entero en una carpeta, aquí
        salta. Es la regresión que esta refactorización existe para evitar."""
        from tools import monitor_protocol

        compartidos = {n for n, v in vars(monitor_protocol.MonitorClient).items()
                       if callable(v) and not n.startswith("__")}
        for prototipo in PROTOTIPOS:
            texto = (ROOT / prototipo / "monitor.py").read_text(encoding="utf8")
            propios = set()
            for nodo in ast.walk(ast.parse(texto)):
                if isinstance(nodo, ast.ClassDef) and nodo.name == "MonitorClient":
                    propios = {h.name for h in nodo.body
                               if isinstance(h, ast.FunctionDef)}
            with self.subTest(prototipo=prototipo):
                self.assertEqual(
                    propios & compartidos, set(),
                    f"{prototipo} reimplementa métodos que ya están en "
                    f"tools/monitor_protocol.py")

    def test_el_cliente_manda_lo_que_su_hardware_atiende(self):
        """Ni de menos ni de más, y lo de más es lo que engaña.

        Un método heredado de balde contra hardware que no lo implementa falla
        con «The FPGA rejected the command», que suena a avería y no a «esta
        placa nunca supo hacer eso».
        """
        for prototipo in PROTOTIPOS:
            cliente = cargar(prototipo).MonitorClient
            for metodo, fichero in OPCIONALES.items():
                tiene_hardware = (ROOT / prototipo / fichero).exists()
                with self.subTest(prototipo=prototipo, metodo=metodo):
                    self.assertEqual(
                        hasattr(cliente, metodo), tiene_hardware,
                        f"{prototipo}: {metodo} {'sobra' if not tiene_hardware else 'falta'}"
                        f" (RTL: {fichero})")

    def test_cada_carpeta_declara_su_propio_mapa(self):
        """Las regiones y el baudrate son lo que distingue a un prototipo, así
        que tienen que seguir estando en su fichero -- y no vacías."""
        for prototipo in PROTOTIPOS:
            monitor = cargar(prototipo)
            with self.subTest(prototipo=prototipo):
                self.assertTrue(monitor.MonitorClient.MEMORY_REGIONS)
                self.assertTrue(monitor.BAUDRATE)
                # `tools/prototype_report.py` las lee del TEXTO, sin importar
                # el módulo, así que tienen que ser asignaciones literales.
                texto = (ROOT / prototipo / "monitor.py").read_text(encoding="utf8")
                self.assertIn("ARCHITECTURAL_REGIONS = (", texto)
                self.assertIn("MONITOR_REGIONS = (", texto)

    def test_la_ventana_del_host_llega_a_donde_llega_el_rtl(self):
        """La gemela que ya se quedó atrás una vez.

        `MONITOR_REGIONS` terminaba en `0x8000_0018` con un comentario que
        decía «llegará a `0x8000_001c` cuando la fase 3.5 añada `VIDEO_CTRL`».
        La fase lo añadió, la constante se quedó, y el host pasó a rechazar un
        bloque sobre el registro que acababa de existir -- `validate_block`
        exige `address + length <= end`, y `0x1c > 0x18`.

        DE DÓNDE SE SACA LO QUE EL RTL ACEPTA. Antes, del `MMIO_PREFIX` de
        20 bits del adaptador: con una sola página de 4 KiB, el prefijo ERA
        la ventana. Con MMIO v2 el adaptador ya no lleva prefijo --mira un
        bit-- y quien decide qué ventanas existen son los parámetros
        `WINDOWn_BASE`/`WINDOWn_END` del `monitor #(...)` de cada `top.v`.

        Ese cambio es una mejora, no un apaño: los `WINDOWn_*` son la gemela
        DE VERDAD de `MONITOR_REGIONS` --el RTL filtra con unos y el host con
        los otros-- mientras que el prefijo del adaptador sólo lo era por
        casualidad, porque coincidían mientras todo cabía en una página.
        """
        ventana = re.compile(
            r"\.WINDOW(\d)_(BASE|END)\s*\(\s*\d+'h([0-9a-fA-F_]+)\s*\)")
        for prototipo in ("16.fpga-cpu-hdmi", "18.fpga-cpu-hdmi-bl8",
                          "19.fpga-cpu-hdmi-ls", "21.fpga-cpu-hdmi-alu"):
            monitor = cargar(prototipo)
            texto = (ROOT / prototipo / "top.v").read_text(encoding="utf8")
            crudas: dict[str, dict[str, int]] = {}
            for indice, extremo, digits in ventana.findall(texto):
                crudas.setdefault(indice, {})[extremo] = int(
                    digits.replace("_", ""), 16)

            # Una ranura sin usar vale 0x1_ffff_ffff en las dos puntas.
            rtl = {(v["BASE"], v["END"]) for v in crudas.values()
                   if "BASE" in v and "END" in v
                   and v["BASE"] != 0x1_FFFF_FFFF}

            with self.subTest(prototipo=prototipo):
                self.assertTrue(rtl, f"{prototipo}: no encuentro WINDOWn_* "
                                     f"en top.v")
                self.assertEqual(
                    rtl, set(monitor.MONITOR_REGIONS),
                    f"{prototipo}: las ventanas del RTL y las de monitor.py no "
                    f"coinciden. El síntoma de esto en la placa es un NACK que "
                    f"parece un bitstream viejo.\n"
                    f"  RTL:      {sorted(rtl)}\n"
                    f"  monitor:  {sorted(monitor.MONITOR_REGIONS)}")

    # Un `sysid.v` declara a qué versión del contrato MMIO pertenece por el
    # magic que lleva dentro. Mismo criterio que
    # `test_monitor_port.test_sysid_es_copia_identica`, para que las carpetas
    # que sigan en v1 no fallen mientras dure la travesía.
    MAGIC_V2 = re.compile(r"MAGIC\s*=\s*32'h4D47_4155", re.IGNORECASE)

    def test_la_ventana_del_cli_cubre_los_bloques_que_decodifica(self):
        """La OTRA gemela, la que se quedó atrás en la 18 y en la 19.

        `monitor.py` guarda la ventana MMIO dos veces y para dos clientes
        distintos:

        - `MONITOR_REGIONS`, que usan `validate_block`/`validate_transfer` y
          que ya tenía dos tests --contra el mapa generado y contra los
          `WINDOWn_*` del `top.v`--.
        - `MMIO_BASE`/`MMIO_LIMIT`, que usa `parse_address`, o sea la LÍNEA DE
          ÓRDENES, y que no miraba nadie.

        Hasta el 20/09/2026 la 18 y la 19 tenían `MMIO_LIMIT = 0x8000_0FFF`,
        que es la página de 4 KiB de v1 y en v2 sólo cubre SYSTEM. Con
        `MONITOR_REGIONS` ya migrado y declarando VIDEO en `0x8020_0000`, el
        mismo fichero afirmaba dos cosas incompatibles: el bloque existe y la
        dirección no es válida. `monitor.py read-word 0x80200000` fallaba sin
        llegar a la placa.

        POR QUÉ NO LO CAZÓ NADIE, y es lo que hace falta recordar: el síntoma
        era `exit=1` con un `Error:`, que es EXACTAMENTE lo que se espera al
        comprobar §4.3 --que un bloque ausente conteste error--. Al medir el
        caso negativo de la 18 (SERIAL ausente) el resto de v1 se lee como la
        confirmación que se venía a buscar. Un test que compara un código de
        salida no habría servido; hay que comparar las constantes.

        La invariante que se fija es interna al fichero y no necesita datos de
        fuera: **la ventana que acepta el CLI tiene que cubrir todas las
        regiones que la propia carpeta declara**. Así vale igual para la 18,
        que tiene tres, que para la 21, que tiene cuatro, sin listar ninguna
        aquí. Y se ancla además contra el mapa generado, para que las dos no
        puedan estar mal a la vez de forma consistente.
        """
        sys.path.insert(0, str(ROOT))
        try:
            from tools.mmio_map import MMIO_SERIAL_BASE, MMIO_SYSTEM_BASE
        finally:
            sys.path.pop(0)

        mirados = 0
        for prototipo in PROTOTIPOS:
            sysid = ROOT / prototipo / "sysid.v"
            if not sysid.exists():
                continue
            if not self.MAGIC_V2.search(sysid.read_text(encoding="utf8")):
                continue        # sigue en v1; le toca cuando migre
            mirados += 1
            monitor = cargar(prototipo)

            # No todas las carpetas filtran direcciones en el host. La 16, la
            # 18, la 19 y la 21 tienen `parse_address`, que rechaza fuera de
            # `MMIO_BASE`/`MMIO_LIMIT`; la 6 y la 10 no lo tienen y su CLI
            # valida con `MAX_ADDRESS` a secas, o sea que la ventana del
            # cliente son los 32 bits enteros y quien rechaza es la placa.
            #
            # La invariante es la MISMA en los dos casos --lo que el CLI
            # acepta tiene que cubrir lo que la carpeta declara-- y se
            # comprueba contra la constante que esa carpeta usa de verdad. Lo
            # que NO se hace es saltarse la carpeta: un filtro cuyo modo de
            # fallo por defecto es no ver es lo que dejó pasar esto la primera
            # vez. Y tampoco se le pide a la 6 que declare un par de
            # constantes que no lee nadie, que es la otra forma de que un dato
            # se quede rancio sin que se note.
            tiene_ventana_propia = hasattr(monitor, "MMIO_BASE")
            if tiene_ventana_propia:
                base, limite = monitor.MMIO_BASE, monitor.MMIO_LIMIT
                with self.subTest(prototipo=prototipo, constante="MMIO_BASE"):
                    self.assertEqual(
                        MMIO_SYSTEM_BASE, base,
                        f"{prototipo}: MMIO_BASE no es la base de SYSTEM del "
                        f"mapa")
            else:
                base, limite = 0, monitor.MAX_ADDRESS
                with self.subTest(prototipo=prototipo, constante="MAX_ADDRESS"):
                    # Si esta carpeta gana un `parse_address` algún día, lo que
                    # hay que hacer es declarar el par, no relajar esto.
                    #
                    # Se mira la DEFINICIÓN con `ast`, no el nombre en el
                    # texto. La primera versión de esta guarda usaba
                    # `assertNotIn` sobre el fuente y saltó contra el
                    # comentario de `6/monitor.py` que explica, precisamente,
                    # que esta carpeta no tiene `parse_address`. Es la misma
                    # regla que `test_mmio_map` aprendió con INT_MIN: no es el
                    # literal lo que distingue una cosa, es el uso.
                    definidas = {
                        nodo.name
                        for nodo in ast.walk(
                            ast.parse(inspect.getsource(monitor)))
                        if isinstance(nodo, ast.FunctionDef)
                    }
                    self.assertNotIn(
                        "parse_address", definidas,
                        f"{prototipo}: define parse_address pero no declara "
                        f"MMIO_BASE/MMIO_LIMIT, así que la ventana que el CLI "
                        f"aplica de verdad no se está comprobando")

            for region_base, region_fin in monitor.MONITOR_REGIONS:
                with self.subTest(prototipo=prototipo,
                                  region=f"{region_base:#010x}"):
                    self.assertTrue(
                        base <= region_base and region_fin - 1 <= limite,
                        f"{prototipo}: la ventana del CLI "
                        f"[{base:#010x}, {limite:#010x}] no cubre la región "
                        f"[{region_base:#010x}, {region_fin - 1:#010x}] que "
                        f"declara MONITOR_REGIONS. El síntoma es que "
                        f"`monitor.py read-word {region_base:#010x}` falla en "
                        f"el HOST, sin llegar a la placa, con un mensaje que "
                        f"se parece demasiado a un error de acceso legítimo.")

            # Donde exista, el puerto serie tiene que estar donde dice el mapa.
            # La 19 lo declaraba en 0x8000_0200, su dirección de v1.
            if hasattr(monitor, "SERIAL_BASE"):
                with self.subTest(prototipo=prototipo, constante="SERIAL_BASE"):
                    self.assertEqual(
                        MMIO_SERIAL_BASE, monitor.SERIAL_BASE,
                        f"{prototipo}: SERIAL_BASE no es la del mapa generado")

        # La guarda de siempre: un test que no mira nada pasa igual, y el modo
        # de fallo por defecto de un filtro es no ver.
        self.assertGreaterEqual(
            mirados, 3, "no se ha mirado ninguna carpeta en v2; ¿ha cambiado "
                        "el magic de sysid.v o la lista de prototipos?")

    def test_el_modelo_de_warps_es_el_de_cada_placa(self):
        """El caso que se escapó: la 12 valida contra 128 KiB de EBR y las
        otras contra 32 MiB de SDRAM. Compartir el valor aceptaba un `pc` que
        en esa placa no existe."""
        esperado = {"12.fpga-gpu": 128 * 1024}
        for prototipo in ("12.fpga-gpu", "14.fpga-gpu-ram",
                          "17.fpga-gpu-ram-v2", "22.fpga-gpu-bl8"):
            cliente = cargar(prototipo).MonitorClient
            with self.subTest(prototipo=prototipo):
                self.assertEqual(cliente.MODEL_MEMORY_SIZE,
                                 esperado.get(prototipo, 32 * 1024 * 1024))


if __name__ == "__main__":
    unittest.main()
