"""tools/prototype.py: localización de apio y parseo de scons.params, sin
depender de que oss-cad-suite ni apio estén instalados de verdad."""

import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.prototype import ToolchainError, find_apio_binary, read_ecp5_params


class FindApioBinaryTest(unittest.TestCase):
    def test_prefers_venv_bin_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apio = root / ".venv" / "bin" / "apio"
            apio.parent.mkdir(parents=True)
            apio.write_text("", encoding="utf-8")
            self.assertEqual(find_apio_binary(root), str(apio))

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
