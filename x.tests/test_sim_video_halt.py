"""`HALT_AT` del simulador cuenta intercambios, como el RTL (mmio.md §9.6).

Es el mismo contrato que prueba `video_registers_tb.v` en cada carpeta de CPU;
aqui se prueba el modelo funcional, que tiene que parar en el mismo sitio.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.sim_devices import VideoDevice


def _video(**kwargs) -> VideoDevice:
    # Un frame por instruccion: cada `tick` es una frontera de frame.
    video = VideoDevice(fb_front=0x1000, fb_back=0x2000, frame_instructions=1, **kwargs)
    video.write(VideoDevice.HALT_TARGET, VideoDevice.HALT_TARGET_CPU)
    return video


def _swap(video: VideoDevice) -> bool:
    """Pide un intercambio y deja que se complete; True si paro la CPU."""
    video.write(VideoDevice.SWAP, 1)
    video.tick()
    return video.halt_request


def _frame_sin_swap(video: VideoDevice) -> bool:
    video.tick()
    return video.halt_request


class HaltAtCuentaIntercambiosTest(unittest.TestCase):
    def test_para_en_el_intercambio_n(self):
        video = _video()
        video.write(VideoDevice.HALT_AT, 2)
        self.assertFalse(_swap(video))
        self.assertTrue(_swap(video))

    def test_los_frames_sin_intercambio_no_cuentan(self):
        # Es lo que cambia respecto a contar frames: un programa lento deja
        # pasar muchos frames por cada swap, y la alarma espera a sus swaps.
        video = _video()
        video.write(VideoDevice.HALT_AT, 1)
        for _ in range(5):
            self.assertFalse(_frame_sin_swap(video))
        self.assertTrue(_swap(video))

    def test_armar_no_toca_los_contadores_del_dispositivo(self):
        video = _video()
        _swap(video)
        _frame_sin_swap(video)
        frames, swaps = video.frame_count, video.swap_count
        self.assertGreater(frames, 0)
        self.assertGreater(swaps, 0)
        video.write(VideoDevice.HALT_AT, 3)
        self.assertEqual(video.read(VideoDevice.FRAME_COUNT), frames)
        self.assertEqual(video.read(VideoDevice.SWAP_COUNT), swaps)

    def test_la_cuenta_es_relativa_al_momento_de_armar(self):
        # Con la cuenta libre un programa solo podria usar la alarma una vez por
        # arranque: la segunda vez el contador ya habria pasado de largo.
        video = _video()
        for _ in range(4):
            _swap(video)
        video.write(VideoDevice.HALT_AT, 2)
        self.assertFalse(_swap(video))
        self.assertTrue(_swap(video))

    def test_es_de_un_disparo(self):
        video = _video()
        video.write(VideoDevice.HALT_AT, 1)
        self.assertTrue(_swap(video))
        self.assertFalse(_swap(video))
        video.write(VideoDevice.HALT_AT, 1)
        self.assertTrue(_swap(video))

    def test_sin_halt_target_no_para_a_nadie(self):
        video = VideoDevice(fb_front=0x1000, fb_back=0x2000, frame_instructions=1)
        video.write(VideoDevice.HALT_AT, 1)
        self.assertFalse(_swap(video))
        self.assertFalse(video.halt_armed, "la alarma se consume igualmente")

    def test_desarmada_no_para(self):
        video = _video()
        self.assertFalse(_swap(video))


if __name__ == "__main__":
    unittest.main()
