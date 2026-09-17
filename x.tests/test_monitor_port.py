"""Deteccion de puerto serie, sin hardware.

`tools/run_board.py` ya filtraba por fabricante, pero los trece `monitor.py` y
`profile.py` iban por su cuenta y cogian el primer puerto del SISTEMA. Eso fallo
de la peor manera posible: con la placa desenchufada la lista empezaba por el
puerto serie de la placa base y dos enlaces Bluetooth, y el sintoma era un
timeout de escritura -- que se parece mucho a "la FPGA no tiene monitor" y nada
a "no has enchufado la placa".

Ahora la logica vive UNA vez en tools/serial_ports.py y los monitores la
importan.
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import serial_ports  # noqa: E402
from backends import board  # noqa: E402


def fake_port(device, vid):
    return SimpleNamespace(device=device, description="serial", vid=vid)


# El orden real que tenia la maquina el dia que esto se rompio: la placa NO es
# el primer puerto, y los dos del medio son Bluetooth.
REAL_WORLD = [
    fake_port("COM1", vid=None),
    fake_port("COM6", vid=0x0A5C),
    fake_port("COM8", vid=0x0A5C),
    fake_port("COM3", vid=serial_ports.FTDI_VENDOR_ID),
]


class DetectPortTest(unittest.TestCase):
    def test_picks_the_ftdi_port_not_the_first_one(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=REAL_WORLD):
            self.assertEqual(serial_ports.detect_port(), "COM3")

    def test_no_ftdi_says_the_board_is_not_connected(self):
        ports = [p for p in REAL_WORLD if p.vid != serial_ports.FTDI_VENDOR_ID]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            with self.assertRaises(serial_ports.PortError) as caught:
                serial_ports.detect_port()
        self.assertIn("no esta conectada", str(caught.exception))

    def test_several_ftdi_asks_which_one(self):
        ports = [
            fake_port("COM3", vid=serial_ports.FTDI_VENDOR_ID),
            fake_port("COM4", vid=serial_ports.FTDI_VENDOR_ID),
        ]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            with self.assertRaises(serial_ports.PortError) as caught:
                serial_ports.detect_port()
        self.assertIn("--port", str(caught.exception))

    def test_available_ports_marks_the_board(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=REAL_WORLD):
            listing = serial_ports.available_ports()
        self.assertIn("COM3 (FTDI)", listing)
        self.assertNotIn("COM1 (FTDI)", listing)

    def test_agrees_with_the_copy_in_backends(self):
        """backends/board.py tiene su propia copia y tiene que decir lo mismo.

        Son dos a proposito: x.tests no depende de tools/ (la dependencia va al
        reves), y board.py recibe el monitor.py del prototipo como modulo, asi
        que un import desde el monitor haria un ciclo.
        """
        self.assertEqual(serial_ports.FTDI_VENDOR_ID, board.FTDI_VENDOR_ID)
        with mock.patch("serial.tools.list_ports.comports", return_value=REAL_WORLD):
            self.assertEqual(serial_ports.detect_port(), board.detect_port())


def load_monitor(prototype_dir: Path):
    path = prototype_dir / "monitor.py"
    spec = importlib.util.spec_from_file_location(
        "monitor_" + prototype_dir.name.replace(".", "_").replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    # Registrarlo ANTES de ejecutarlo: @dataclass mira sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MONITORS = sorted(ROOT.glob("*/monitor.py"), key=lambda p: p.parent.name)


class EveryMonitorTest(unittest.TestCase):
    """Los trece monitores, no solo el ultimo.

    El fallo original estaba en los trece a la vez; una prueba que solo mire el
    prototipo en el que se trabaja hoy no habria dicho nada.
    """

    def test_there_are_monitors_to_check(self):
        self.assertGreaterEqual(len(MONITORS), 13)

    def test_all_share_the_common_detection(self):
        for path in MONITORS:
            with self.subTest(prototype=path.parent.name):
                module = load_monitor(path.parent)
                self.assertIs(module.detect_port, serial_ports.detect_port)
                self.assertIs(module.available_ports, serial_ports.available_ports)

    def test_none_defaults_to_a_hardcoded_com_port(self):
        for path in MONITORS:
            with self.subTest(prototype=path.parent.name):
                self.assertNotIn('default="COM3"', path.read_text(encoding="utf8"))


GPU_PROTOTYPES = (
    "12.fpga-gpu",
    "14.fpga-gpu-ram",
    "17.fpga-gpu-ram-v2",
    "22.fpga-gpu-bl8",
)

# Una ranura de ventana sin usar. La base es inalcanzable para una direccion de
# 32 bits, asi que la comparacion nunca se cumple.
UNUSED_WINDOW = (0x1_FFFF_FFFF, 0x0)

PARAMETER = re.compile(r"\.(\w+)\(33'h([0-9a-fA-F_]+)\)")


def monitor_instantiations(prototype: Path):
    """Los parametros de cada `monitor #(...)` del prototipo, por fichero."""
    for path in sorted(prototype.glob("*.v")):
        if path.name == "monitor.v":
            continue        # ahi el `#(` es la DECLARACION, no una instancia
        source = path.read_text(encoding="utf8")
        for match in re.finditer(r"\bmonitor\s*#\(", source):
            # emparejar parentesis: la lista lleva unos cuantos dentro
            depth, cursor = 1, match.end()
            while depth and cursor < len(source):
                depth += {"(": 1, ")": -1}.get(source[cursor], 0)
                cursor += 1
            values = {
                name: int(digits.replace("_", ""), 16)
                for name, digits in PARAMETER.findall(source[match.end():cursor])
            }
            yield path, values


def rtl_windows(values: dict) -> set:
    windows = set()
    for slot in range(4):
        window = (values[f"WINDOW{slot}_BASE"], values[f"WINDOW{slot}_END"])
        if window != UNUSED_WINDOW:
            windows.add(window)
    return windows


class SharedMonitorTest(unittest.TestCase):
    """Los cuatro monitor.v de la familia GPU son COPIA IDENTICA.

    Se decidio copia y no fichero compartido para que cada carpeta siga siendo
    autocontenida. Lo que antes los diferenciaba --version, tamano de RAM y la
    lista de ventanas MMIO-- son ahora parametros que pone el top, asi que no
    queda ninguna razon legitima para que el texto difiera. Si diverge otra vez,
    salta aqui.
    """

    def test_las_cuatro_copias_son_identicas(self):
        canonical = (ROOT / "22.fpga-gpu-bl8" / "monitor.v").read_bytes()
        for name in GPU_PROTOTYPES:
            with self.subTest(prototype=name):
                self.assertEqual((ROOT / name / "monitor.v").read_bytes(), canonical)


class MonitorRegionsTest(unittest.TestCase):
    """Las ventanas del cliente tienen que ser las mismas que las del RTL.

    La lista vive DOS veces: en Python (MONITOR_REGIONS) y en los parametros que
    el top pasa al monitor. Anadir una ventana en un sitio y no en el otro es
    exactamente lo que dejo 0x200 y 0x300 rechazados en placa mientras en
    simulacion todo pasaba.
    """

    def test_python_and_rtl_agree(self):
        for name in GPU_PROTOTYPES:
            prototype = ROOT / name
            esperadas = set(load_monitor(prototype).MONITOR_REGIONS)
            instancias = list(monitor_instantiations(prototype))
            self.assertTrue(instancias, f"{name} no instancia monitor con parametros")
            for path, values in instancias:
                with self.subTest(prototype=name, fichero=path.name):
                    self.assertEqual(rtl_windows(values), esperadas)

    def test_todas_las_instancias_de_un_prototipo_coinciden(self):
        """La 22 tiene dos tops y un banco de pruebas; los tres han de decir lo
        mismo, o se depura un mapa que no es el que esta sintetizado."""
        for name in GPU_PROTOTYPES:
            with self.subTest(prototype=name):
                valores = [v for _, v in monitor_instantiations(ROOT / name)]
                for otros in valores[1:]:
                    self.assertEqual(otros, valores[0])


if __name__ == "__main__":
    unittest.main()
