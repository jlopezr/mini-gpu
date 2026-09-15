import os
import tempfile
import unittest
from pathlib import Path

from tools.prototype import PrototypeResolutionError, resolve_prototype

REPO = Path(__file__).resolve().parents[1]


class PrototypeResolutionTest(unittest.TestCase):
    def test_resolve_by_number(self):
        self.assertEqual(resolve_prototype("17", REPO).name, "17.fpga-gpu-ram-v2")

    def test_resolve_by_name(self):
        self.assertEqual(resolve_prototype("17.fpga-gpu-ram-v2", REPO).name, "17.fpga-gpu-ram-v2")

    def test_resolve_relative_path(self):
        expected = (REPO / "17.fpga-gpu-ram-v2").resolve()
        self.assertEqual(resolve_prototype("./17.fpga-gpu-ram-v2", REPO), expected)

    def test_resolve_absolute_path(self):
        expected = (REPO / "17.fpga-gpu-ram-v2").resolve()
        self.assertEqual(resolve_prototype(str(expected), REPO), expected)

    def test_missing_prototype_raises_clear_error(self):
        with self.assertRaises(PrototypeResolutionError):
            resolve_prototype("999", REPO)

    def test_ambiguous_prototype_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "17.alpha").mkdir()
            (root / "17.beta").mkdir()
            with self.assertRaises(PrototypeResolutionError):
                resolve_prototype("17", root)

    def test_root_resolution_uses_repo_layout(self):
        # Hay que volver al cwd original ANTES de salir del with: Windows no
        # deja borrar un directorio que es el cwd de un proceso vivo, así que
        # un addCleanup (que corre después) rompería el borrado del tempdir.
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                self.assertEqual(resolve_prototype("17", REPO).name, "17.fpga-gpu-ram-v2")
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
