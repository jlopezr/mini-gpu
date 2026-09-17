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
