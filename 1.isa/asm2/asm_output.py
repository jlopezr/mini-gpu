#!/usr/bin/env python3
"""Assembly output writers.

The assembler produces an AssemblyResult; this module knows how to serialize it
to concrete files. Keeping this separate makes room for future object-like
formats without mixing writer policy into parsing/layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Callable, Protocol


class HasImage(Protocol):
    image: bytes
    sections: dict[str, Any]
    symbols: dict[str, Any]
    relocations: list[Any]


@dataclass(frozen=True)
class OutputFormat:
    name: str
    extension: str
    write: Callable[[HasImage, Path], None]


def default_output(source: Path, suffix: str = ".bin") -> Path:
    """Default generated output lives in _build next to the source."""
    return source.parent / "_build" / source.with_suffix(suffix).name


def write_binary_image(image: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image)


def write_hex_image(image: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii") as f:
        for index in range(0, len(image), 4):
            word = int.from_bytes(image[index:index + 4], "little")
            f.write(f"{word:08X}\n")


def write_bin(result: HasImage, path: Path) -> None:
    write_binary_image(result.image, path)


def write_hex(result: HasImage, path: Path) -> None:
    write_hex_image(result.image, path)


VOBJ_MAGIC = b"VOBJ"
VOBJ_LITTLE_ENDIAN = 2
VOBJ_CPU = "minigpu"
VOBJ_BITS_PER_BYTE = 8
VOBJ_BYTES_PER_ADDR = 4
VOBJ_LABSYM = 1
VOBJ_EXPRESSION = 3
VOBJ_REL_ABS = 1
VOBJ_REL_PC = 2


def _write_vobj_number(stream: BytesIO, value: int, *, signed: bool = False) -> None:
    if not signed and value < 0:
        raise ValueError(f"VOBJ unsigned number cannot be negative: {value}")
    if not signed and value <= 0x7f:
        stream.write(bytes([value]))
        return
    if signed and 0 <= value <= 0x7f:
        stream.write(bytes([value]))
        return

    for size in range(1, VOBJ_BYTES_PER_ADDR + 1):
        if signed:
            low = -(1 << (size * 8 - 1))
            high = (1 << (size * 8 - 1)) - 1
            if low <= value <= high:
                encoded = (value & ((1 << (size * 8)) - 1)).to_bytes(size, "little")
                break
        elif value <= (1 << (size * 8)) - 1:
            encoded = value.to_bytes(size, "little")
            break
    else:
        kind = "signed" if signed else "unsigned"
        raise ValueError(f"VOBJ {kind} number does not fit in {VOBJ_BYTES_PER_ADDR} bytes: {value}")

    stream.write(bytes([0x80 + len(encoded)]))
    stream.write(encoded)


def _write_vobj_string(stream: BytesIO, value: str) -> None:
    raw = value.encode("utf-8")
    if b"\x00" in raw:
        raise ValueError(f"VOBJ string contains NUL byte: {value!r}")
    stream.write(raw + b"\x00")


def _vobj_section_attr(name: str, section: Any) -> str:
    if name == ".text":
        return "acx"
    if name == ".rodata":
        return "ad"
    if name == ".bss" or getattr(section, "bss_size", 0):
        return "auw"
    if name == ".data":
        return "adw"
    return "ad"


def _vobj_section_size(name: str, section: Any) -> int:
    if name == ".bss" or getattr(section, "bss_size", 0):
        return int(getattr(section, "bss_size", 0)) or len(section.data)
    return len(section.data)


def _signed_taddr(value: int) -> int:
    value &= 0xFFFFFFFF
    if value & 0x80000000:
        return value - 0x100000000
    return value


def _write_vobj_symbol(stream: BytesIO, symbol: Any, section_indexes: dict[str, int]) -> None:
    _write_vobj_string(stream, symbol.name)
    if symbol.section is None or getattr(symbol, "kind", "") == "absolute":
        _write_vobj_number(stream, VOBJ_EXPRESSION)
        _write_vobj_number(stream, 0)
        _write_vobj_number(stream, 0)
    else:
        _write_vobj_number(stream, VOBJ_LABSYM)
        _write_vobj_number(stream, 0)
        _write_vobj_number(stream, section_indexes[symbol.section])
    _write_vobj_number(stream, int(symbol.offset), signed=True)
    _write_vobj_number(stream, 0)


def _vobj_relocation_type(relocation: Any) -> int:
    if relocation.kind == "PCREL_WORD":
        return VOBJ_REL_PC
    return VOBJ_REL_ABS


def _write_vobj_relocation(stream: BytesIO, relocation: Any,
                           symbol_indexes: dict[str, int],
                           symbols_by_name: dict[str, Any]) -> None:
    try:
        symbol_index = symbol_indexes[relocation.symbol]
        symbol = symbols_by_name[relocation.symbol]
    except KeyError:
        raise ValueError(
            f"relocation references unknown VOBJ symbol: {relocation.symbol}"
        ) from None
    if symbol.section is None:
        raise ValueError(
            f"VOBJ relocation cannot reference absolute symbol: {relocation.symbol}"
        )
    addend = int(getattr(symbol, "offset", 0)) + int(getattr(relocation, "addend", 0))
    _write_vobj_number(stream, _vobj_relocation_type(relocation))
    _write_vobj_number(stream, int(relocation.offset))
    _write_vobj_number(stream, int(getattr(relocation, "bit_offset", 0)))
    _write_vobj_number(stream, int(getattr(relocation, "bit_size", 32)))
    _write_vobj_number(stream, _signed_taddr(int(getattr(relocation, "mask", 0xFFFFFFFF))),
                       signed=True)
    _write_vobj_number(stream, addend, signed=True)
    _write_vobj_number(stream, symbol_index)


def encode_vobj(result: HasImage) -> bytes:
    sections = list(result.sections.values())
    section_indexes = {section.name: index for index, section in enumerate(sections, start=1)}
    symbols = [symbol for symbol in result.symbols.values() if getattr(symbol, "defined", True)]
    symbol_indexes = {symbol.name: index for index, symbol in enumerate(symbols, start=1)}
    symbols_by_name = {symbol.name: symbol for symbol in symbols}
    relocs_by_section: dict[str, list[Any]] = {section.name: [] for section in sections}
    for relocation in result.relocations:
        relocs_by_section.setdefault(relocation.section, []).append(relocation)

    stream = BytesIO()
    stream.write(VOBJ_MAGIC)
    stream.write(bytes([VOBJ_LITTLE_ENDIAN]))
    _write_vobj_number(stream, VOBJ_BITS_PER_BYTE)
    _write_vobj_number(stream, VOBJ_BYTES_PER_ADDR)
    _write_vobj_string(stream, VOBJ_CPU)
    _write_vobj_number(stream, len(sections))
    _write_vobj_number(stream, len(symbols))

    for symbol in symbols:
        _write_vobj_symbol(stream, symbol, section_indexes)

    for section in sections:
        attr = _vobj_section_attr(section.name, section)
        data = b"" if "u" in attr else bytes(section.data)
        relocs = relocs_by_section.get(section.name, [])
        _write_vobj_string(stream, section.name)
        _write_vobj_string(stream, attr)
        _write_vobj_number(stream, 0)
        _write_vobj_number(stream, int(section.alignment))
        _write_vobj_number(stream, _vobj_section_size(section.name, section))
        _write_vobj_number(stream, len(relocs))
        _write_vobj_number(stream, len(data))
        stream.write(data)
        for relocation in relocs:
            _write_vobj_relocation(stream, relocation, symbol_indexes, symbols_by_name)

    return stream.getvalue()


def write_vobj(result: HasImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_vobj(result))


def source_to_json(source: Any) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "file": source.file,
        "line": source.line,
        "column": source.column,
    }


def section_to_json(section: Any) -> dict[str, Any]:
    return {
        "name": section.name,
        "alignment": section.alignment,
        "bss_size": section.bss_size,
        "size": len(section.data),
        "data": bytes(section.data).hex(),
    }


def symbol_to_json(symbol: Any) -> dict[str, Any]:
    return {
        "name": symbol.name,
        "section": symbol.section,
        "offset": symbol.offset,
        "binding": symbol.binding,
        "kind": symbol.kind,
        "defined": symbol.defined,
        "source": source_to_json(symbol.source),
    }


def relocation_to_json(relocation: Any) -> dict[str, Any]:
    return {
        "section": relocation.section,
        "offset": relocation.offset,
        "symbol": relocation.symbol,
        "kind": relocation.kind,
        "addend": relocation.addend,
        "bit_offset": getattr(relocation, "bit_offset", 0),
        "bit_size": getattr(relocation, "bit_size", 32),
        "mask": getattr(relocation, "mask", 0xFFFFFFFF),
        "resolved": relocation.resolved,
        "source": source_to_json(relocation.source),
    }


def json_document(result: HasImage) -> dict[str, Any]:
    return {
        "magic": "MiniGPU-Object",
        "version": 1,
        "format": "resolved-flat-object",
        "entry": 0,
        "image_size": len(result.image),
        "image": result.image.hex(),
        "sections": {
            name: section_to_json(section)
            for name, section in result.sections.items()
        },
        "symbols": {
            name: symbol_to_json(symbol)
            for name, symbol in result.symbols.items()
        },
        "relocations": [
            relocation_to_json(relocation)
            for relocation in result.relocations
        ],
    }


def write_json(result: HasImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_document(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


FORMATS: dict[str, OutputFormat] = {
    "bin": OutputFormat("bin", ".bin", write_bin),
    "hex": OutputFormat("hex", ".hex", write_hex),
    "json": OutputFormat("json", ".json", write_json),
    "vobj": OutputFormat("vobj", ".vobj", write_vobj),
}


def write_output(result: HasImage, path: Path, output_format: str = "bin") -> None:
    try:
        writer = FORMATS[output_format].write
    except KeyError:
        known = ", ".join(sorted(FORMATS))
        raise ValueError(f"formato de salida desconocido: {output_format} ({known})") from None
    writer(result, path)
