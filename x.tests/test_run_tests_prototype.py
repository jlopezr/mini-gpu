"""Selección de versiones del runner mediante prototipos."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from run_tests import version_for_prototype  # noqa: E402


class PrototypeVersionTests(unittest.TestCase):
    def test_cpu_prototype_number_selects_alias(self):
        self.assertEqual(
            version_for_prototype("21", ("cpu-fpga",)),
            ("cpu-fpga", "alu"),
        )

    def test_gpu_prototype_number_selects_alias(self):
        self.assertEqual(
            version_for_prototype("22", ("gpu-fpga",)),
            ("gpu-fpga", "lsu2"),
        )

    def test_both_targets_only_hardware_backend(self):
        self.assertEqual(
            version_for_prototype("21", ("cpusim", "cpu-fpga")),
            ("cpu-fpga", "alu"),
        )

    def test_simulator_rejects_prototype(self):
        with self.assertRaisesRegex(ValueError, "solo se puede usar"):
            version_for_prototype("21", ("cpusim",))

    def test_wrong_architecture_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no es una versión registrada"):
            version_for_prototype("22", ("cpu-fpga",))


if __name__ == "__main__":
    unittest.main()
