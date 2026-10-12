#!/usr/bin/env python3
"""Tests for the MiniGPU VOBJ inspector."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import asm_output


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mini_objdump", HERE / "mini-objdump.py")
mini_objdump = importlib.util.module_from_spec(spec)
assert spec.loader is not None
# Registrado antes de ejecutarlo: sus dataclass buscan su modulo en sys.modules.
sys.modules[spec.name] = mini_objdump
spec.loader.exec_module(mini_objdump)


@dataclass
class Section:
    name: str
    data: bytearray
    alignment: int = 4
    bss_size: int = 0


@dataclass
class Symbol:
    name: str
    section: str | None
    offset: int
    binding: str = "local"
    kind: str = "label"
    defined: bool = True


@dataclass
class Relocation:
    section: str
    offset: int
    symbol: str
    kind: str
    addend: int = 0
    bit_offset: int = 0
    bit_size: int = 32
    mask: int = 0xFFFFFFFF


@dataclass
class Result:
    image: bytes
    sections: dict[str, Section]
    symbols: dict[str, Symbol]
    relocations: list[Relocation]


class MiniObjdumpTest(unittest.TestCase):
    def make_vobj(self) -> bytes:
        result = Result(
            image=bytes.fromhex("000000fc"),
            sections={".text": Section(".text", bytearray(bytes.fromhex("000000fc")))},
            symbols={
                "start": Symbol("start", ".text", 0, binding="global"),
                "external": Symbol("external", None, 0, binding="global",
                                   kind="extern", defined=False),
            },
            relocations=[Relocation(".text", 0, "external", "ABS32", addend=4)],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "program.o"
            asm_output.write_output(result, path, "vobj")
            return path.read_bytes()

    def test_parse_vobj_symbols_sections_and_relocations(self):
        obj = mini_objdump.parse_vobj(self.make_vobj())

        self.assertEqual(obj.cpu, "minigpu")
        self.assertEqual(obj.symbols[0].name, "start")
        self.assertEqual(obj.symbols[0].flags, 8)
        self.assertEqual(obj.symbols[1].type, 2)
        self.assertEqual(obj.sections[0].name, ".text")
        self.assertEqual(obj.sections[0].relocs[0].symbol, 2)

    def test_format_can_include_disassembly(self):
        obj = mini_objdump.parse_vobj(self.make_vobj())
        text = mini_objdump.format_vobj(obj, disassemble=True)

        self.assertIn("Symbols:", text)
        self.assertIn("external", text)
        self.assertIn("reloc ABS", text)
        self.assertIn("HALT", text)


if __name__ == "__main__":
    unittest.main()
