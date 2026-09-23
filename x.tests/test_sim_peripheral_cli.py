"""Contrato de las opciones CLI comunes de los simuladores."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.sim_peripherals import from_arguments


def arguments(**overrides):
    values = dict(
        video=False,
        frame_output=None,
        frame_instructions=1000,
        halt_after_swaps=None,
        serial=False,
        serial_input=None,
        serial_output=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class SimPeripheralCliTest(unittest.TestCase):
    def test_halt_after_swaps_uses_swap_counter_not_halt_at(self):
        video = from_arguments(arguments(halt_after_swaps=3))["video"]

        self.assertEqual(video.stop_after_swaps, 3)
        self.assertFalse(video.halt_armed)
        self.assertEqual(video.halt_at, 0)

    def test_halt_after_swaps_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "debe ser positivo"):
            from_arguments(arguments(halt_after_swaps=0))


if __name__ == "__main__":
    unittest.main()
