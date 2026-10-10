"""La fase de la PLL de la 35 y su valor por defecto en `version.json`.

Sin placa: un cliente falso imita el bloque MMIO `phase_mmio.v` (la posición solo
avanza, dando la vuelta a las 48 posiciones).
"""

import json
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from backends import board, fpga_cpu  # noqa: E402
from backends.common import load_module  # noqa: E402

FOLDER = REPOSITORY / "35.fpga-cpu-fifo-sdram2"
monitor = load_module("monitor_35_for_phase_tests", FOLDER / "monitor.py")


class PhaseController:
    """Los registros de `phase_mmio.v` que usa el cliente."""

    def __init__(self, position=0, locked=True):
        self.position = position
        self.locked = locked
        self.moves = []

    def read_word(self, address):
        assert address == monitor.PHASE_STATUS
        return (self.position << 8) | (4 if self.locked else 0) | 8

    def write_word(self, address, value):
        assert address == monitor.PHASE_CTRL and value & 1
        steps = (value >> 8) & 0x3F
        self.moves.append(steps)
        self.position = (self.position + steps) % monitor.PHASES


class FakeClient(monitor.PhaseMixin, PhaseController):
    pass


class SetPhaseTest(unittest.TestCase):
    def test_avanza_hasta_la_fase_pedida(self):
        client = FakeClient(position=0)
        self.assertEqual(client.set_sdram_phase(10)["pos"], 10)
        self.assertEqual(client.moves, [10])

    def test_da_la_vuelta_porque_solo_avanza(self):
        client = FakeClient(position=40)
        client.set_sdram_phase(4)
        self.assertEqual(client.moves, [12])
        self.assertEqual(client.position, 4)

    def test_si_ya_esta_no_escribe(self):
        client = FakeClient(position=10)
        client.set_sdram_phase(10)
        self.assertEqual(client.moves, [])

    def test_rechaza_una_fase_fuera_de_rango(self):
        for bad in (-1, 48):
            with self.subTest(phase=bad), self.assertRaises(monitor.MonitorError):
                FakeClient().set_sdram_phase(bad)

    def test_rechaza_una_pll_sin_enganchar(self):
        with self.assertRaises(monitor.MonitorError):
            FakeClient(locked=False).set_sdram_phase(5)


class VersionJsonTest(unittest.TestCase):
    def write(self, directory, content):
        path = Path(directory) / "version.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        return path

    def test_aplica_sdram_phase(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, {"alias": "x", "sdram_phase": 7})
            self.assertEqual(client.apply_version_settings(path), 7)
        self.assertEqual(client.position, 7)

    def test_sin_el_campo_no_toca_nada(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, {"alias": "x"})
            self.assertIsNone(client.apply_version_settings(path))
        self.assertEqual(client.moves, [])

    def test_la_35_fija_una_fase_valida(self):
        phase = json.loads((FOLDER / "version.json").read_text(encoding="utf-8"))["sdram_phase"]
        self.assertTrue(0 <= phase < monitor.PHASES)


class ConnectAppliesSettingsTest(unittest.TestCase):
    """`MonitorBackend.connect` aplica los ajustes del prototipo al abrir."""

    def backend(self, client):
        Version = namedtuple("Version", "major minor")

        class Port:
            def __init__(self, **options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        client.get_version = lambda: Version(*self.expected)
        fake_monitor = SimpleNamespace(
            serial=SimpleNamespace(Serial=Port, EIGHTBITS=8, PARITY_NONE="N", STOPBITS_ONE=1),
            BAUDRATE=115200, MonitorClient=lambda connection: client)
        with mock.patch.object(board, "ensure_bitstream"):
            backend = fpga_cpu.FpgaCpuBackend(REPOSITORY, "COM3", 1.0, version="sdram2")
        backend.monitor = fake_monitor
        self.expected = backend.configuration["monitor_version"]
        client.get_version = lambda: Version(*self.expected)
        return backend

    def test_aplica_la_fase_al_conectar(self):
        client = FakeClient()
        with self.backend(client).connect():
            pass
        self.assertEqual(client.position, 10)

    def test_un_monitor_sin_ajustes_no_falla(self):
        client = SimpleNamespace()
        with self.backend(client).connect():
            pass


if __name__ == "__main__":
    unittest.main()
