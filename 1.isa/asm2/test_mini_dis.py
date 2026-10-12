#!/usr/bin/env python3
"""Tests for mini-dis."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import minigpu_isa as isa


HERE = Path(__file__).resolve().parent


def load_disassembler():
    spec = importlib.util.spec_from_file_location("new_mini_dis", HERE / "mini-dis.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mini_dis = load_disassembler()


class DisassembleTest(unittest.TestCase):
    def test_disassemble_words_with_addresses_and_encoded_words(self):
        words = [
            isa.encode("ADD", Rd=1, Ra=2, Rb=3),
            isa.encode("GETLANE", Rd=4),
        ]
        self.assertEqual(
            mini_dis.disassemble_words(words),
            "\n".join([
                "00000000  04221800  ADD R1, R2, R3",
                "00000004  c0810000  GETLANE R4",
            ]),
        )

    def test_branch_uses_pc_for_target(self):
        word = isa.encode("BEQ", Ra=1, Rb=2, target=1)
        self.assertEqual(
            mini_dis.disassemble_words([word], start_pc=0x20),
            "00000020  80220001  BEQ R1, R2, 0x00000028",
        )

    def test_unknown_encoding_is_word(self):
        text = mini_dis.disassemble_words([0x34 << 26])
        self.assertEqual(text, "00000000  d0000000  .word 0xD0000000")

    def test_can_hide_columns(self):
        word = isa.encode("HALT")
        self.assertEqual(
            mini_dis.disassemble_words([word], show_addresses=False, show_words=False),
            "HALT",
        )


class InputTest(unittest.TestCase):
    def test_reads_binary_and_hex_files(self):
        words = [isa.encode("NOP"), isa.encode("HALT")]
        image = b"".join(word.to_bytes(4, "little") for word in words)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_path = root / "program.bin"
            hex_path = root / "program.hex"
            bin_path.write_bytes(image)
            hex_path.write_text("00000000\nFC000000\n", encoding="ascii")

            self.assertEqual(mini_dis.read_words(bin_path), words)
            self.assertEqual(mini_dis.read_words(hex_path), words)

    def test_rejects_partial_binary_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.bin"
            path.write_bytes(b"\x00")
            with self.assertRaises(mini_dis.DisasmError):
                mini_dis.read_words(path)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "program.hex"
            path.write_text("FC000000\n", encoding="ascii")
            result = subprocess.run(
                [sys.executable, str(HERE / "mini-dis.py"), str(path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HALT", result.stdout)


if __name__ == "__main__":
    unittest.main()
