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
    def test_read_reg_parses_a_word(self):
        with mock.patch.object(capture_frames, "run_monitor_cli",
                               return_value="Address 0x80200004: 0x12345678"):
            value = capture_frames.read_reg(Path("/proto"), "COM3",
                                            capture_frames.FB_FRONT)
        self.assertEqual(value, 0x12345678)

    def test_read_reg_rejects_unexpected_output(self):
        with mock.patch.object(capture_frames, "run_monitor_cli", return_value="garbage"):
            with self.assertRaises(SystemExit):
                capture_frames.read_reg(Path("/proto"), "COM3", 0x80200004)

    def test_write_reg_sends_one_word_command(self):
        # Y no cuatro `write-byte`: escribir HALT_AT en trozos lo rearma cuatro
        # veces con valores intermedios y la captura se dispara donde no toca
        # (el hazard que describe `mmio_decoder.v` nombrando a esta
        # herramienta).
        calls = []
        with mock.patch.object(capture_frames, "run_monitor_cli",
                               side_effect=lambda p, port, *a: calls.append(a)):
            capture_frames.write_reg(Path("/proto"), "COM3",
                                     capture_frames.STATUS, 0x01)
        self.assertEqual(calls, [("write-word", "0x80200010", "1")])


class CaptureFramesAddressTest(unittest.TestCase):
    """Las direcciones, contra el mapa generado.

    Es el test que faltaba: las de aquí se quedaron en el mapa v1 cuando la
    migración movió la ventana de vídeo, y probar sólo el parseo de respuestas
    no lo coge --una dirección equivocada da una respuesta igual de válida--.
    """

    def test_registers_match_the_generated_map(self):
        from tools.mmio_map import (
            MMIO_VIDEO_BASE, MMIO_VIDEO_FB_FRONT_OFF, MMIO_VIDEO_HALT_AT_OFF,
            MMIO_VIDEO_HALT_TARGET_OFF, MMIO_VIDEO_STATUS_OFF,
            MMIO_VIDEO_SWAP_COUNT_OFF,
        )

        esperado = {
            "FB_FRONT": MMIO_VIDEO_BASE + MMIO_VIDEO_FB_FRONT_OFF,
            "STATUS": MMIO_VIDEO_BASE + MMIO_VIDEO_STATUS_OFF,
            "SWAP_COUNT": MMIO_VIDEO_BASE + MMIO_VIDEO_SWAP_COUNT_OFF,
            "HALT_AT": MMIO_VIDEO_BASE + MMIO_VIDEO_HALT_AT_OFF,
            "HALT_TARGET": MMIO_VIDEO_BASE + MMIO_VIDEO_HALT_TARGET_OFF,
        }
        for nombre, direccion in esperado.items():
            self.assertEqual(getattr(capture_frames, nombre), direccion, nombre)

    def test_video_window_is_not_the_system_window(self):
        from tools.mmio_map import MMIO_SYSTEM_BASE, MMIO_VIDEO_BASE

        # El fallo concreto que hubo: leer FB_FRONT en 0x80000000, que en v2
        # devuelve el magic de SYS_ID con pinta de dirección de framebuffer.
        self.assertNotEqual(MMIO_VIDEO_BASE, MMIO_SYSTEM_BASE)
        self.assertGreaterEqual(capture_frames.FB_FRONT, MMIO_VIDEO_BASE)

    def test_halt_target_is_armed_before_halt_at(self):
        calls = []
        with mock.patch.object(capture_frames, "run_monitor_cli",
                               side_effect=lambda p, port, *a: calls.append(a)):
            capture_frames.arm_halt(Path("/proto"), "COM3", 7)
        direcciones = [int(a[1], 16) for a in calls]
        self.assertEqual(direcciones,
                         [capture_frames.HALT_TARGET, capture_frames.HALT_AT])
        self.assertEqual(calls[-1][2], "7")


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
