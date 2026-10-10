"""Selección de versiones del runner mediante prototipos."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from run_tests import version_for_prototype  # noqa: E402


class PrototypeVersionTests(unittest.TestCase):
    def test_cpu_prototype_number_selects_alias(self):
        self.assertEqual(
            version_for_prototype("21", ("fpga-cpu",)),
            ("fpga-cpu", "alu"),
        )

    def test_gpu_prototype_number_selects_alias(self):
        self.assertEqual(
            version_for_prototype("22", ("fpga-gpu",)),
            ("fpga-gpu", "lsu2"),
        )

    def test_both_targets_only_hardware_backend(self):
        self.assertEqual(
            version_for_prototype("21", ("sim-cpu", "fpga-cpu")),
            ("fpga-cpu", "alu"),
        )

    def test_simulator_rejects_prototype(self):
        with self.assertRaisesRegex(ValueError, "solo se puede usar"):
            version_for_prototype("21", ("sim-cpu",))

    def test_wrong_architecture_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no es una versión registrada"):
            version_for_prototype("22", ("fpga-cpu",))


if __name__ == "__main__":
    unittest.main()
