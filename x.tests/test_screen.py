"""Composición de pantalla (`tools/screen.py`) contra la referencia `render_rgb`."""
import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))

from tools import console_render, screen
from tools.sim_devices import VideoDevice
import minicpu_sim


def random_font(seed=1):
    rng = random.Random(seed)
    return [rng.getrandbits(128) for _ in range(256)]


def random_scene(seed=2):
    rng = random.Random(seed)
    text = [rng.getrandbits(16) for _ in range(80 * 30)]
    palette = [0] + [rng.getrandbits(24) for _ in range(255)]
    framebuffer = bytes(rng.getrandbits(8) for _ in range(screen.FRAME_BYTES))
    return text, palette, framebuffer


class CompositorTest(unittest.TestCase):
    def test_texto_sobre_framebuffer_igual_que_la_referencia(self):
        font = random_font()
        text, palette, framebuffer = random_scene()
        snap = {"mode": screen.MODE_SCANOUT, "fb": framebuffer, "text": text, "palette": palette}
        expected = console_render.render_rgb(text, palette, font, framebuffer)
        self.assertEqual(screen.Compositor(font).compose(snap).tobytes(), expected)

    def test_texto_sin_framebuffer_igual_que_la_referencia(self):
        font = random_font(3)
        text, palette, _ = random_scene(4)
        for mode in (screen.MODE_BLANK, screen.MODE_SCANOUT):       # SCANOUT sin fb: negro
            snap = {"mode": mode, "fb": None, "text": text, "palette": palette}
            expected = console_render.render_rgb(text, palette, font, None)
            self.assertEqual(screen.Compositor(font).compose(snap).tobytes(), expected)

    def test_solo_framebuffer(self):
        _, _, framebuffer = random_scene(5)
        snap = {"mode": screen.MODE_SCANOUT, "fb": framebuffer, "text": None, "palette": None}
        expected = console_render.render_rgb([0] * 2400, [0] * 256, random_font(), framebuffer)
        self.assertEqual(screen.Compositor(random_font()).compose(snap).tobytes(), expected)

    def test_blank_es_negro(self):
        snap = {"mode": screen.MODE_BLANK, "fb": None, "text": None, "palette": None}
        image = screen.Compositor(random_font()).compose(snap)
        self.assertEqual(image.size, (640, 480))
        self.assertEqual(image.getextrema(), ((0, 0), (0, 0), (0, 0)))

    def test_pattern_son_barras_y_no_es_negro(self):
        snap = {"mode": screen.MODE_PATTERN, "fb": None, "text": None, "palette": None}
        image = screen.Compositor(random_font()).compose(snap)
        self.assertEqual(image.getpixel((10, 10)), (255, 255, 255))
        self.assertEqual(image.getpixel((639, 479)), (0, 0, 0))
        self.assertNotEqual(image.getextrema(), ((0, 0), (0, 0), (0, 0)))

    def test_el_color_cero_es_transparente(self):
        font = [0xFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF] * 256        # glifo todo a uno
        palette = [0] * 256
        palette[1] = 0x00FF00
        text = [0x0100] + [0] * (2400 - 1)          # fg = 1 (verde), bg = 0 (transparente)
        _, _, framebuffer = random_scene(6)
        snap = {"mode": screen.MODE_SCANOUT, "fb": framebuffer, "text": text, "palette": palette}
        image = screen.Compositor(font).compose(snap)
        self.assertEqual(image.getpixel((3, 3)), (0, 255, 0))           # el glifo
        reference = screen.Compositor(font).compose({**snap, "text": None})
        self.assertEqual(image.getpixel((100, 100)), reference.getpixel((100, 100)))

    def test_rapido_tras_el_primer_frame(self):
        font = random_font()
        text, palette, framebuffer = random_scene()
        snap = {"mode": screen.MODE_SCANOUT, "fb": framebuffer, "text": text, "palette": palette}
        compositor = screen.Compositor(font)
        compositor.compose(snap)                                    # llena la caché
        start = time.perf_counter()
        for _ in range(5):
            compositor.compose(snap)
        per_frame = (time.perf_counter() - start) / 5
        self.assertLess(per_frame, 0.25, f"{per_frame * 1000:.0f} ms por frame")


class SnapshotTest(unittest.TestCase):
    def machine(self, **video_options):
        video = VideoDevice(console=video_options.pop("console", False))
        cpu = minicpu_sim.CPU(1 << 20, video=video)
        return cpu, video

    def test_sin_video_falla_con_motivo(self):
        with self.assertRaises(ValueError):
            screen.snapshot(minicpu_sim.CPU(1 << 20))

    def test_scanout_copia_el_framebuffer_frontal(self):
        cpu, video = self.machine()
        video.video_mode = VideoDevice.MODE_SCANOUT
        video.fb_front = 0x1000
        cpu.memory[0x1000:0x1004] = b"\x12\x34\x56\x78"
        snap = screen.snapshot(cpu)
        self.assertEqual(snap["mode"], screen.MODE_SCANOUT)
        self.assertEqual(snap["fb"][:4], b"\x12\x34\x56\x78")
        self.assertEqual(len(snap["fb"]), screen.FRAME_BYTES)
        self.assertIsNone(snap["text"])

    def test_pattern_no_lleva_framebuffer(self):
        cpu, video = self.machine()
        video.video_mode = VideoDevice.MODE_PATTERN
        self.assertIsNone(screen.snapshot(cpu)["fb"])

    def test_framebuffer_fuera_de_ram_no_revienta(self):
        cpu, video = self.machine()
        video.video_mode = VideoDevice.MODE_SCANOUT
        video.fb_front = len(cpu.memory) - 16
        self.assertIsNone(screen.snapshot(cpu)["fb"])

    def test_el_texto_solo_sale_con_text_enable(self):
        cpu, video = self.machine(console=True)
        video.text_ram[0] = 0x0141
        self.assertIsNone(screen.snapshot(cpu)["text"])
        video.config_active = VideoDevice.CONFIG_TEXT_ENABLE
        snap = screen.snapshot(cpu)
        self.assertEqual(snap["text"][0], 0x0141)
        self.assertEqual(len(snap["palette"]), 256)

    def test_sin_consola_nunca_hay_texto(self):
        cpu, video = self.machine()
        video.config_active = VideoDevice.CONFIG_TEXT_ENABLE
        self.assertIsNone(screen.snapshot(cpu)["text"])


if __name__ == "__main__":
    unittest.main()
