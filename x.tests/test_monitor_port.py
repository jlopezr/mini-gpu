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


class MonitorRegionsTest(unittest.TestCase):
    """Las ventanas del cliente tienen que ser las mismas que las del RTL.

    La lista vive DOS veces: en Python (MONITOR_REGIONS) y en la funcion
    `block_range_valid` de monitor.v. Anadir una ventana en un sitio y no en el
    otro es exactamente lo que dejo 0x200 y 0x300 rechazados en placa mientras
    en simulacion todo pasaba.
    """

    def test_python_and_rtl_agree(self):
        prototype = ROOT / "22.fpga-gpu-bl8"
        monitor = load_monitor(prototype)
        source = (prototype / "monitor.v").read_text(encoding="utf8")
        for start, end in monitor.MONITOR_REGIONS:
            if start < 0x8000_0000:
                continue        # la SDRAM se escribe con otro formato en el RTL
            for label, value in (("inicio", start), ("final", end)):
                needle = f"33'h0_{value >> 16:04x}_{value & 0xFFFF:04x}"
                self.assertIn(needle, source,
                              f"el {label} {value:#x} no esta en monitor.v")


if __name__ == "__main__":
    unittest.main()
