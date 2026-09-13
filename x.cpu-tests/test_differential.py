"""Pruebas del recorte que hace el diferencial `--backend both`.

El modo `both` ejecuta cada caso en el simulador y en la FPGA y compara los dos
estados observados. Eso solo sirve si lo que compara PUEDE coincidir: un campo
que es distinto por construccion convierte el diferencial en un fallo fijo, y un
fallo fijo se acaba ignorando, que es la peor forma de perder una comprobacion.

Los tres casos de video fallaban siempre el diferencial --pasando los dos
backends por separado-- por dos campos asi. Estas pruebas fijan el recorte para
que no vuelva a colarse, y sobre todo para que quede claro que lo que se recorta
es lo que no puede coincidir, no lo que resulta incomodo: el frame capturado,
`swaps` y `fb_front` se siguen comparando byte a byte.
"""

import unittest

from run_gpu_tests import comparable


def _resultado(**extra):
    base = {
        "halted": True,
        "error": False,
        "error_code": 0,
        "pc": 0x20,
        "registers": {1: 7},
        "memory": {},
        "video": None,
        "cycles": None,
        "instructions": 42,
        "clock_hz": None,
    }
    base.update(extra)
    return base


class ComparableTest(unittest.TestCase):

    def test_los_campos_de_rendimiento_no_se_comparan(self):
        """El simulador no tiene ciclos ni reloj, y no va a tenerlos."""
        sim = _resultado(cycles=None, instructions=42, clock_hz=None)
        fpga = _resultado(cycles=9001, instructions=42, clock_hz=80_000_000)
        self.assertEqual(comparable(sim, {}), comparable(fpga, {}))

    def test_el_contador_de_frames_no_se_compara(self):
        """Un frame aqui son N instrucciones; en la placa, 16,7 ms de barrido.

        Los dos numeros son correctos y no pueden coincidir. Medido en
        `video-registers`: 1 contra 7068.
        """
        sim = _resultado(video={"underflow": False, "frames": 1, "swaps": 4,
                                "fb_front": 0x0100_0000, "frame": b"ab"})
        fpga = _resultado(video={"underflow": False, "frames": 7068, "swaps": 4,
                                 "fb_front": 0x0100_0000, "frame": b"ab"})
        self.assertEqual(comparable(sim, {}), comparable(fpga, {}))

    def test_el_resto_del_video_si_se_compara(self):
        """Y es lo que de verdad dice si las dos hacen lo mismo."""
        sim = _resultado(video={"underflow": False, "frames": 1, "swaps": 4,
                                "fb_front": 0x0100_0000, "frame": b"ab"})
        for campo, otro in (("swaps", 5),
                            ("fb_front", 0x0102_5800),
                            ("frame", b"xy"),
                            ("underflow", True)):
            with self.subTest(campo=campo):
                fpga = _resultado(video=dict(sim["video"], **{campo: otro}))
                self.assertNotEqual(comparable(sim, {}), comparable(fpga, {}))

    def test_el_pc_se_compara_cuando_la_parada_es_determinista(self):
        """Sin `run_until` el programa para en su HALT: el PC tiene que cuadrar."""
        sim = _resultado(pc=0x20)
        fpga = _resultado(pc=0x24)
        self.assertNotEqual(comparable(sim, {}), comparable(fpga, {}))

    def test_el_pc_no_se_compara_con_run_until(self):
        """Ahi la parada es asincrona y el PC queda donde pille a la CPU.

        Es el mismo motivo por el que `parse_run_until` prohibe declarar
        `expect.pc` junto a `run_until`. Medido en `video-bounce`: 196 contra
        192, dos instrucciones del bucle de espera.
        """
        sim = _resultado(pc=196)
        fpga = _resultado(pc=192)
        caso = {"run_until": {"swap": 4}}
        self.assertEqual(comparable(sim, caso), comparable(fpga, caso))

    def test_un_caso_sin_video_no_se_rompe(self):
        """`video` es None en la mayoria de los casos."""
        self.assertIsNone(comparable(_resultado(), {})["video"])

    def test_el_recorte_no_modifica_el_resultado_original(self):
        """El runner sigue usando `results` despues, para medir."""
        original = _resultado(video={"underflow": False, "frames": 1,
                                     "swaps": 4, "fb_front": 0, "frame": None})
        comparable(original, {"run_until": {"swap": 4}})
        self.assertEqual(original["video"]["frames"], 1)
        self.assertEqual(original["instructions"], 42)
        self.assertEqual(original["pc"], 0x20)


if __name__ == "__main__":
    unittest.main()
