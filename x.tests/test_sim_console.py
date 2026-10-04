"""Consola de texto 80x30 del simulador funcional (30.fpga-cpu-console).

El contrato es el de `video_registers.v`: CONFIG con shadow/active, paleta y
texto en RAM propia, y SWAP como FRAME_COMMIT de dos bits. Sin `console=True`
esas direcciones siguen sin existir, como en el resto de prototipos.
"""
from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import console_render
from tools.sim_devices import VideoDevice
from tools.sim_peripherals import resolve_font

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


class RenderTest(unittest.TestCase):
    """`tools/console_render.py`: lo que hace `text_console.v`, con una fuente de juguete."""

    @staticmethod
    def _font():
        font = [0] * 256
        font[0x41] = 0x80  # solo el pixel superior izquierdo
        return font

    @staticmethod
    def _px(rgb, x, y):
        return tuple(rgb[(y * 640 + x) * 3:(y * 640 + x) * 3 + 3])

    def test_glifo_con_primer_plano_y_fondo(self):
        palette = [0] * 256
        palette[1], palette[2] = 0xFF0000, 0x0000FF
        cells = [0] * 2400
        cells[0] = (2 << 12) | (1 << 8) | 0x41
        rgb = console_render.render_rgb(cells, palette, self._font())
        self.assertEqual(self._px(rgb, 0, 0), (255, 0, 0))
        self.assertEqual(self._px(rgb, 1, 0), (0, 0, 255))

    def test_color_cero_es_transparente(self):
        palette = [0] * 256
        palette[1] = 0xFF0000
        cells = [0] * 2400
        cells[0] = (0 << 12) | (1 << 8) | 0x41  # fondo 0: deja ver lo de debajo
        blanco = b"\xff\xff" * (320 * 240)
        sin_fb = console_render.render_rgb(cells, palette, self._font())
        con_fb = console_render.render_rgb(cells, palette, self._font(), blanco)
        self.assertEqual(self._px(sin_fb, 1, 0), (0, 0, 0))
        self.assertEqual(self._px(con_fb, 1, 0), (255, 255, 255))
        self.assertEqual(self._px(con_fb, 0, 0), (255, 0, 0))

    def test_color_cero_en_primer_plano_tambien_es_transparente(self):
        # El fallo que tenia el TUI: texto "negro" = indice 0 = se ve el fondo.
        palette = [0] * 256
        palette[7] = 0xAAAAAA
        cells = [0] * 2400
        cells[0] = (7 << 12) | (0 << 8) | 0x41
        blanco = b"\xff\xff" * (320 * 240)
        rgb = console_render.render_rgb(cells, palette, self._font(), blanco)
        self.assertEqual(self._px(rgb, 0, 0), (255, 255, 255))
        self.assertEqual(self._px(rgb, 1, 0), (0xAA, 0xAA, 0xAA))

    def test_framebuffer_se_escala_2x(self):
        fb = bytearray(320 * 240 * 2)
        fb[0], fb[1] = 0x00, 0xF8  # RGB565 0xF800 little-endian: rojo
        rgb = console_render.render_rgb([0] * 2400, [0] * 256, [0] * 256, bytes(fb))
        for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
            self.assertEqual(self._px(rgb, x, y), (255, 0, 0))
        self.assertEqual(self._px(rgb, 2, 0), (0, 0, 0))

    def test_png_valido(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pantalla.png"
            console_render.write_png(path, bytes(640 * 480 * 3))
            data = path.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (640, 480))

    def test_fuentes_por_nombre(self):
        for name in ("pc", "cpc464", "tamzen"):
            self.assertEqual(len(console_render.load_font(resolve_font(name))), 256)
        with self.assertRaises(ValueError):
            resolve_font("no-existe")


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

    def test_imagen_de_la_consola(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys = Path(tmp) / "keys.bin"
            image = Path(tmp) / "pantalla.png"
            keys.write_bytes(b"\x1b")
            result = subprocess.run(
                [sys.executable, str(ROOT / "2.cpu-sim-func" / "minicpu_sim.py"),
                 str(DEMO_BIN), "--serial-input", str(keys),
                 "--console-image", str(image), "--console-font", "tamzen",
                 "--max", "50000000"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = image.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (640, 480))


if __name__ == "__main__":
    unittest.main()
