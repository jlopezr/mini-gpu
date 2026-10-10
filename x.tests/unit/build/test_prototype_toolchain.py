"""tools/prototype.py: localización de apio y parseo de scons.params, sin
depender de que oss-cad-suite ni apio estén instalados de verdad."""

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.prototype import ToolchainError, find_apio_binary, read_ecp5_params

# El layout de un venv depende del SO: `Scripts/apio.exe` en Windows,
# `bin/apio` en Linux/macOS. Las pruebas montan el del intérprete que las
# ejecuta, no uno fijo, porque find_apio_binary hace la misma distinción.
VENV_DIR = "Scripts" if os.name == "nt" else "bin"
APIO = "apio.exe" if os.name == "nt" else "apio"


def make_apio(root: Path, subdirectory: str, filename: str = APIO) -> Path:
    path = root / ".venv" / subdirectory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


class FindApioBinaryTest(unittest.TestCase):
    def test_prefers_venv_over_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apio = make_apio(root, VENV_DIR)
            self.assertEqual(find_apio_binary(root), str(apio))

    def test_scripts_wins_over_bin_when_both_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = make_apio(root, "Scripts")
            make_apio(root, "bin")
            self.assertEqual(find_apio_binary(root), str(scripts))

    def test_ignores_the_other_platform_layout(self):
        # Un `bin/apio` de POSIX no es ejecutable en Windows, ni un
        # `Scripts/apio.exe` en Linux: en ambos casos hay que caer al PATH.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if os.name == "nt":
                make_apio(root, "bin", "apio")
            else:
                make_apio(root, "Scripts", "apio.exe")
            self.assertEqual(find_apio_binary(root), "apio")

    def test_falls_back_to_path_when_no_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_apio_binary(Path(tmp)), "apio")


class ReadEcp5ParamsTest(unittest.TestCase):
    def test_extracts_type_package_speed(self):
        text = textwrap.dedent("""
            some_other_block {
                foo: "bar"
            }
            ecp5_params {
                type: "85k"
                package: "CABGA381"
                speed: "6"
            }
        """)
        self.assertEqual(read_ecp5_params(text), {"type": "85k", "package": "CABGA381", "speed": "6"})

    def test_missing_ecp5_params_block_raises(self):
        with self.assertRaises(ToolchainError):
            read_ecp5_params("some_other_block { foo: \"bar\" }")

    def test_missing_field_raises(self):
        text = 'ecp5_params { type: "85k" package: "CABGA381" }'
        with self.assertRaises(ToolchainError):
            read_ecp5_params(text)


if __name__ == "__main__":
    unittest.main()
