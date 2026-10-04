"""Consola de texto 80x30 del simulador funcional (30.fpga-cpu-console).

El contrato es el de `video_registers.v`: CONFIG con shadow/active, paleta y
texto en RAM propia, y SWAP como FRAME_COMMIT de dos bits. Sin `console=True`
esas direcciones siguen sin existir, como en el resto de prototipos.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.sim_devices import VideoDevice

DEMO_BIN = ROOT / "z.tui" / "_build" / "tui_mini.bin"


def _console() -> VideoDevice:
    return VideoDevice(frame_instructions=1, console=True)


class ConsolaTest(unittest.TestCase):
    def test_sin_consola_las_direcciones_no_existen(self):
        video = VideoDevice()
        for offset in (VideoDevice.CONFIG, VideoDevice.PALETTE_BASE,
                       VideoDevice.TEXT_BASE):
            with self.assertRaises(RuntimeError):
                video.write(offset, 0)

    def test_paleta_y_texto_se_leen_como_se_escriben(self):
        video = _console()
        video.write(VideoDevice.PALETTE_BASE + 4 * 15, 0x00FFFFFF)
        video.write(VideoDevice.TEXT_BASE + 4 * 81, 0x0F41)
        self.assertEqual(video.read(VideoDevice.PALETTE_BASE + 4 * 15), 0x00FFFFFF)
        self.assertEqual(video.text_lines()[1][1], "A")

    def test_fuera_de_las_ventanas_es_error(self):
        video = _console()
        with self.assertRaises(RuntimeError):
            video.write(VideoDevice.TEXT_BASE + 4 * VideoDevice.TEXT_WORDS, 0)
        with self.assertRaises(RuntimeError):
            video.write(VideoDevice.PALETTE_BASE + 4 * VideoDevice.PALETTE_WORDS, 0)

    def test_config_solo_se_activa_con_state_commit(self):
        video = _console()
        video.write(VideoDevice.CONFIG, VideoDevice.CONFIG_TEXT_ENABLE)
        self.assertEqual(video.read(VideoDevice.CONFIG), VideoDevice.CONFIG_TEXT_ENABLE)
        self.assertEqual(video.config_active, 0)
        video.write(VideoDevice.SWAP, VideoDevice.STATE_COMMIT)
        self.assertEqual(video.read(VideoDevice.SWAP), VideoDevice.STATE_COMMIT)
        video.tick()
        self.assertEqual(video.config_active, VideoDevice.CONFIG_TEXT_ENABLE)
        self.assertEqual(video.read(VideoDevice.SWAP), 0)

    def test_state_commit_no_pide_intercambio(self):
        video = _console()
        video.write(VideoDevice.SWAP, VideoDevice.STATE_COMMIT)
        video.tick()
        self.assertEqual(video.swap_count, 0)

    def test_escrituras_invalidas_son_error_y_no_surten_efecto(self):
        video = _console()
        with self.assertRaises(RuntimeError):
            video.write(VideoDevice.CONFIG, 8)
        self.assertEqual(video.read(VideoDevice.CONFIG), 0)
        with self.assertRaises(RuntimeError):
            video.write(VideoDevice.SWAP, 4)
        video.write(VideoDevice.SWAP, VideoDevice.STATE_COMMIT)
        with self.assertRaises(RuntimeError):
            video.write(VideoDevice.SWAP, VideoDevice.STATE_COMMIT)


@unittest.skipUnless(DEMO_BIN.exists(), "z.tui/_build/tui_mini.bin no está construido")
class DemoTuiTest(unittest.TestCase):
    """La demo de z.tui: la pila de 8 KiB no cabía con `App` como local de main."""

    def test_arranca_dibuja_y_sale_con_esc(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys = Path(tmp) / "keys.bin"
            screen = Path(tmp) / "screen.txt"
            keys.write_bytes(b"\x1b")
            result = subprocess.run(
                [sys.executable, str(ROOT / "2.cpu-sim-func" / "minicpu_sim.py"),
                 str(DEMO_BIN), "--serial-input", str(keys),
                 "--console-output", str(screen), "--max", "50000000"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("ERROR", result.stdout)
            lines = screen.read_text(encoding="utf-8").splitlines()
            self.assertIn("File", lines[0])
            self.assertIn("F1 Help", lines[29])


if __name__ == "__main__":
    unittest.main()
