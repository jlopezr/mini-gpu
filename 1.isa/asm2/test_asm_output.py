#!/usr/bin/env python3
"""Tests for assembly output writers."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import asm_output


@dataclass
class Result:
    image: bytes
    sections: dict[str, object] | None = None
    symbols: dict[str, object] | None = None
    relocations: list[object] | None = None

    def __post_init__(self):
        if self.sections is None:
            self.sections = {}
        if self.symbols is None:
            self.symbols = {}
        if self.relocations is None:
            self.relocations = []


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
    source: object | None = None
    kind: str = "label"
    defined: bool = True


@dataclass
class Relocation:
    section: str
    offset: int
    symbol: str
    kind: str
    addend: int = 0
    source: object | None = None
    resolved: bool = True
    bit_offset: int = 0
    bit_size: int = 32
    mask: int = 0xFFFFFFFF


class VobjReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def number(self, signed: bool = False) -> int:
        first = self.read(1)[0]
        if first <= 0x7F:
            return first
        size = first - 0x80
        raw = self.read(size)
        return int.from_bytes(raw, "little", signed=signed)

    def string(self) -> str:
        end = self.data.index(0, self.offset)
        value = self.data[self.offset:end].decode("utf-8")
        self.offset = end + 1
        return value


def read_vobj_summary(data: bytes) -> dict[str, object]:
    reader = VobjReader(data)
    magic = reader.read(4)
    endian = reader.read(1)[0]
    bits_per_byte = reader.number()
    bytes_per_addr = reader.number()
    cpu = reader.string()
    section_count = reader.number()
    symbol_count = reader.number()
    symbols = []
    for _ in range(symbol_count):
        symbols.append({
            "name": reader.string(),
            "type": reader.number(),
            "flags": reader.number(),
            "section": reader.number(),
            "value": reader.number(signed=True),
            "size": reader.number(),
        })
    sections = []
    for _ in range(section_count):
        name = reader.string()
        attr = reader.string()
        flags = reader.number()
        align = reader.number()
        size = reader.number()
        reloc_count = reader.number()
        data_size = reader.number()
        reader.read(data_size)
        relocs = []
        for _ in range(reloc_count):
            relocs.append({
                "type": reader.number(),
                "offset": reader.number(),
                "bit_offset": reader.number(),
                "bit_size": reader.number(),
                "mask": reader.number(signed=True),
                "addend": reader.number(signed=True),
                "symbol": reader.number(),
            })
        sections.append({
            "name": name,
            "attr": attr,
            "flags": flags,
            "align": align,
            "size": size,
            "relocs": relocs,
        })
    return {
        "magic": magic,
        "endian": endian,
        "bits_per_byte": bits_per_byte,
        "bytes_per_addr": bytes_per_addr,
        "cpu": cpu,
        "symbols": symbols,
        "sections": sections,
    }


class OutputWriterTest(unittest.TestCase):
    def test_default_output_uses_build_directory(self):
        self.assertEqual(
            asm_output.default_output(Path("case/program.asm")),
            Path("case/_build/program.bin"),
        )

    def test_writes_binary_and_hex(self):
        result = Result(bytes.fromhex("00000000 000000fc"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_path = root / "out" / "program.bin"
            hex_path = root / "out" / "program.hex"

            asm_output.write_output(result, bin_path, "bin")
            asm_output.write_output(result, hex_path, "hex")

            self.assertEqual(bin_path.read_bytes(), result.image)
            self.assertEqual(hex_path.read_text(encoding="ascii"), "00000000\nFC000000\n")

    def test_writes_vobj(self):
        result = Result(
            image=bytes.fromhex("00000000 000000fc"),
            sections={
                ".text": Section(".text", bytearray(bytes.fromhex("00000000 000000fc"))),
            },
            symbols={
                "start": Symbol("start", ".text", 0),
                "table": Symbol("table", ".text", 4),
            },
            relocations=[
                Relocation(".text", 0, "start", "ABS32"),
                Relocation(".text", 4, "table", "ABS16", addend=8, bit_size=16, mask=0xFFFF),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "program.vobj"
            asm_output.write_output(result, path, "vobj")
            data = path.read_bytes()
            summary = read_vobj_summary(data)

        self.assertEqual(data[:5], b"VOBJ\x02")
        self.assertIn(b"minigpu\x00", data)
        self.assertIn(b"start\x00", data)
        self.assertIn(b".text\x00acx\x00", data)
        self.assertEqual(summary["magic"], b"VOBJ")
        self.assertEqual(summary["cpu"], "minigpu")
        self.assertEqual(summary["sections"][0]["relocs"][0]["type"], 1)
        self.assertEqual(summary["sections"][0]["relocs"][0]["symbol"], 1)
        self.assertEqual(summary["sections"][0]["relocs"][1]["addend"], 12)

    def test_writes_json_object_with_relocations(self):
        result = Result(
            image=bytes.fromhex("000000fc"),
            sections={".text": Section(".text", bytearray(bytes.fromhex("000000fc")))},
            symbols={"start": Symbol("start", ".text", 0)},
            relocations=[Relocation(".text", 0, "start", "ABS32")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "program.json"
            asm_output.write_output(result, path, "json")
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["magic"], "MiniGPU-Object")
        self.assertEqual(data["relocations"][0]["symbol"], "start")
        self.assertEqual(data["relocations"][0]["kind"], "ABS32")

    def test_unknown_format_is_reported(self):
        with self.assertRaises(ValueError):
            asm_output.write_output(Result(b""), Path("out.elf"), "elf")


if __name__ == "__main__":
    unittest.main()
