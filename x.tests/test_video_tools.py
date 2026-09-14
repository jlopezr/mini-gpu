"""capture-frames / measure-demo: parseo de registros, sin placa real.

Ambos viven en tools/ sin extensión .py (como el resto de lanzadores), así
que se cargan con importlib, igual que run_board.load_monitor carga
monitor.py."""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = ROOT / "tools" / name
    module_name = name.replace("-", "_")
    loader = importlib.machinery.SourceFileLoader(module_name, str(path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


capture_frames = _load("capture-frames")
measure_demo = _load("measure-demo")


class CaptureFramesRegisterTest(unittest.TestCase):
    def test_read_reg_assembles_little_endian_bytes(self):
        responses = [
            "Address 0x80000000: 0x78",
            "Address 0x80000001: 0x56",
            "Address 0x80000002: 0x34",
            "Address 0x80000003: 0x12",
        ]
        with mock.patch.object(capture_frames, "run_monitor_cli", side_effect=responses):
            value = capture_frames.read_reg(Path("/proto"), "COM3", 0x80000000)
        self.assertEqual(value, 0x12345678)

    def test_read_reg_rejects_unexpected_output(self):
        with mock.patch.object(capture_frames, "run_monitor_cli", return_value="garbage"):
            with self.assertRaises(SystemExit):
                capture_frames.read_reg(Path("/proto"), "COM3", 0x80000000)

    def test_write_reg_sends_four_write_byte_commands(self):
        calls = []
        with mock.patch.object(capture_frames, "run_monitor_cli",
                               side_effect=lambda p, port, *a: calls.append(a)):
            capture_frames.write_reg(Path("/proto"), "COM3", 0x8000000C, 0x01)
        self.assertEqual(calls, [
            ("write-byte", "0x8000000c", "1"),
            ("write-byte", "0x8000000d", "0"),
            ("write-byte", "0x8000000e", "0"),
            ("write-byte", "0x8000000f", "0"),
        ])


class MeasureDemoRegisterTest(unittest.TestCase):
    def test_read_band_extracts_decimal_value(self):
        with mock.patch.object(measure_demo, "run_monitor_cli",
                               return_value="R21 = 0x0000002a (42)\n"):
            self.assertEqual(measure_demo.read_band(Path("/proto"), "COM3"), 42)

    def test_read_band_rejects_unexpected_output(self):
        with mock.patch.object(measure_demo, "run_monitor_cli", return_value="garbage"):
            with self.assertRaises(SystemExit):
                measure_demo.read_band(Path("/proto"), "COM3")

    def test_wrap_constant_matches_r21_period(self):
        # R21 avanza de dos en dos y da la vuelta cada 112 frames: el periodo
        # en unidades de registro es 224, no un numero elegido a mano.
        self.assertEqual(measure_demo.WRAP, 224)


if __name__ == "__main__":
    unittest.main()
