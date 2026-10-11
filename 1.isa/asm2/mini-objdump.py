#!/usr/bin/env python3
"""Inspect MiniGPU VOBJ object files."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import isa


class VobjError(ValueError):
    """Invalid or unsupported VOBJ input."""


@dataclass(frozen=True)
class VobjSymbol:
    index: int
    name: str
    type: int
    flags: int
    section: int
    value: int
    size: int


@dataclass(frozen=True)
class VobjRelocation:
    type: int
    offset: int
    bit_offset: int
    bit_size: int
    mask: int
    addend: int
    symbol: int


@dataclass(frozen=True)
class VobjSection:
    index: int
    name: str
    attr: str
    flags: int
    align: int
    size: int
    data: bytes
    relocs: tuple[VobjRelocation, ...]


@dataclass(frozen=True)
class VobjFile:
    endian: str
    bits_per_byte: int
    bytes_per_addr: int
    cpu: str
    symbols: tuple[VobjSymbol, ...]
    sections: tuple[VobjSection, ...]


class VobjReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.byteorder = "little"

    def read(self, size: int) -> bytes:
        if self.offset + size > len(self.data):
            raise VobjError("fin de fichero inesperado")
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def number(self, signed: bool = False) -> int:
        first = self.read(1)[0]
        if first <= 0x7F:
            return first
        size = first - 0x80
        raw = self.read(size)
        return int.from_bytes(raw, self.byteorder, signed=signed)

    def string(self) -> str:
        try:
            end = self.data.index(0, self.offset)
        except ValueError:
            raise VobjError("cadena VOBJ sin terminador NUL") from None
        try:
            value = self.data[self.offset:end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise VobjError(f"cadena VOBJ no es UTF-8: {error}") from None
        self.offset = end + 1
        return value


SYMBOL_TYPES = {
    1: "LABSYM",
    2: "IMPORT",
    3: "EXPRESSION",
}

SYMBOL_FLAGS = {
    8: "EXPORT",
    16: "INEVAL",
    32: "COMMON",
    64: "WEAK",
}

RELOC_TYPES = {
    1: "ABS",
    2: "PC",
}


def flag_names(value: int, known: dict[int, str]) -> str:
    names = [name for bit, name in sorted(known.items()) if value & bit]
    unknown = value & ~sum(known)
    if unknown:
        names.append(f"0x{unknown:x}")
    return "|".join(names) if names else "-"


def symbol_type_name(value: int) -> str:
    return SYMBOL_TYPES.get(value, f"type-{value}")


def reloc_type_name(value: int) -> str:
    return RELOC_TYPES.get(value, f"type-{value}")


def parse_vobj(data: bytes) -> VobjFile:
    reader = VobjReader(data)
    if reader.read(4) != b"VOBJ":
        raise VobjError("magic VOBJ ausente")
    endian_flag = reader.read(1)[0]
    if endian_flag == 1:
        reader.byteorder = "big"
        endian = "big"
    elif endian_flag == 2:
        reader.byteorder = "little"
        endian = "little"
    else:
        raise VobjError(f"endianness VOBJ desconocida: {endian_flag}")

    bits_per_byte = reader.number()
    bytes_per_addr = reader.number()
    cpu = reader.string()
    section_count = reader.number()
    symbol_count = reader.number()

    symbols = []
    for index in range(1, symbol_count + 1):
        symbols.append(VobjSymbol(
            index=index,
            name=reader.string(),
            type=reader.number(),
            flags=reader.number(),
            section=reader.number(),
            value=reader.number(signed=True),
            size=reader.number(),
        ))

    sections = []
    for index in range(1, section_count + 1):
        name = reader.string()
        attr = reader.string()
        flags = reader.number()
        align = reader.number()
        size = reader.number()
        reloc_count = reader.number()
        data_size = reader.number()
        section_data = reader.read(data_size)
        relocs = []
        for _ in range(reloc_count):
            relocs.append(VobjRelocation(
                type=reader.number(),
                offset=reader.number(),
                bit_offset=reader.number(),
                bit_size=reader.number(),
                mask=reader.number(signed=True),
                addend=reader.number(signed=True),
                symbol=reader.number(),
            ))
        sections.append(VobjSection(
            index=index,
            name=name,
            attr=attr,
            flags=flags,
            align=align,
            size=size,
            data=section_data,
            relocs=tuple(relocs),
        ))

    if reader.offset != len(data):
        raise VobjError(f"{len(data) - reader.offset} bytes sobrantes al final")

    return VobjFile(
        endian=endian,
        bits_per_byte=bits_per_byte,
        bytes_per_addr=bytes_per_addr,
        cpu=cpu,
        symbols=tuple(symbols),
        sections=tuple(sections),
    )


def read_vobj(path: Path) -> VobjFile:
    try:
        return parse_vobj(path.read_bytes())
    except OSError as error:
        raise VobjError(f"no se puede leer {path}: {error}") from None


def symbol_name(obj: VobjFile, index: int) -> str:
    if 1 <= index <= len(obj.symbols):
        return obj.symbols[index - 1].name
    if index == 0:
        return "<section-base>"
    return f"<symbol-{index}>"


def format_vobj(obj: VobjFile, *, disassemble: bool = False) -> str:
    lines = [
        "VOBJ",
        f"  cpu: {obj.cpu}",
        f"  endian: {obj.endian}",
        f"  address: {obj.bits_per_byte}-bit bytes, {obj.bytes_per_addr} bytes/taddr",
        f"  sections: {len(obj.sections)}",
        f"  symbols: {len(obj.symbols)}",
    ]

    lines.append("")
    lines.append("Symbols:")
    if obj.symbols:
        for sym in obj.symbols:
            lines.append(
                f"  [{sym.index:>2}] {sym.name:<24} "
                f"{symbol_type_name(sym.type):<10} "
                f"flags={flag_names(sym.flags, SYMBOL_FLAGS):<12} "
                f"sec={sym.section:<2} value=0x{sym.value & 0xFFFFFFFF:08x} "
                f"size={sym.size}"
            )
    else:
        lines.append("  <none>")

    lines.append("")
    lines.append("Sections:")
    for section in obj.sections:
        lines.append(
            f"  [{section.index:>2}] {section.name:<12} "
            f"attr={section.attr:<4} flags=0x{section.flags:x} "
            f"align={section.align} size={section.size} "
            f"data={len(section.data)} relocs={len(section.relocs)}"
        )
        for reloc in section.relocs:
            lines.append(
                f"       reloc {reloc_type_name(reloc.type):<4} "
                f"off=0x{reloc.offset:08x} bits={reloc.bit_offset}:{reloc.bit_size} "
                f"mask=0x{reloc.mask & 0xFFFFFFFF:08x} "
                f"addend={reloc.addend} "
                f"symbol=[{reloc.symbol}] {symbol_name(obj, reloc.symbol)}"
            )
        if disassemble and "x" in section.attr and section.data:
            lines.append("       disassembly:")
            if len(section.data) % 4:
                lines.append("         <section data is not 32-bit aligned>")
            else:
                words = [
                    int.from_bytes(section.data[i:i + 4], obj.endian)
                    for i in range(0, len(section.data), 4)
                ]
                for index, word in enumerate(words):
                    pc = index * 4
                    text = isa.disassemble_word(word, pc)
                    lines.append(f"         {pc:08x}  {word & 0xFFFFFFFF:08x}  {text}")

    return "\n".join(lines)


def vobj_to_json(obj: VobjFile) -> dict[str, object]:
    data = asdict(obj)
    for section in data["sections"]:
        section["data"] = section["data"].hex()
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspecciona objetos VOBJ MiniGPU")
    parser.add_argument("input", type=Path, help="fichero .vobj/.o")
    parser.add_argument("-d", "--disassemble", action="store_true",
                        help="desensambla secciones ejecutables con datos")
    parser.add_argument("--json", action="store_true",
                        help="emite el contenido parseado como JSON")
    args = parser.parse_args(argv)

    try:
        obj = read_vobj(args.input)
    except VobjError as error:
        raise SystemExit(f"error: {error}") from None

    if args.json:
        print(json.dumps(vobj_to_json(obj), indent=2, sort_keys=True))
    else:
        print(format_vobj(obj, disassemble=args.disassemble))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
