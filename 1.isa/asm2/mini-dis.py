#!/usr/bin/env python3
"""MiniISA disassembler."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import isa


class DisasmError(ValueError):
    """Invalid disassembler input."""


def read_hex_words(path: Path) -> list[int]:
    words: list[int] = []
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        raise DisasmError(f"no se puede leer {path}: {error}") from None

    for number, raw in enumerate(lines, 1):
        token = raw.strip()
        if not token:
            continue
        try:
            value = int(token, 16)
        except ValueError:
            raise DisasmError(
                f"{path}:{number}: palabra hexadecimal invalida: {token}"
            ) from None
        if not 0 <= value <= 0xFFFFFFFF:
            raise DisasmError(
                f"{path}:{number}: palabra fuera de 32 bits: {token}"
            )
        words.append(value)
    return words


def read_binary_words(path: Path) -> list[int]:
    try:
        image = path.read_bytes()
    except OSError as error:
        raise DisasmError(f"no se puede leer {path}: {error}") from None

    if len(image) % 4:
        raise DisasmError(
            f"{path}: el binario no contiene palabras completas de 32 bits"
        )

    return [
        int.from_bytes(image[index:index + 4], "little")
        for index in range(0, len(image), 4)
    ]


def read_words(path: Path, input_format: str = "auto") -> list[int]:
    suffix = path.suffix.lower()
    if input_format == "hex" or (input_format == "auto" and suffix == ".hex"):
        return read_hex_words(path)
    if input_format in {"bin", "auto"}:
        return read_binary_words(path)
    raise DisasmError(f"formato de entrada desconocido: {input_format}")


def disassemble_words(words: Iterable[int], start_pc: int = 0,
                      show_words: bool = True,
                      show_addresses: bool = True) -> str:
    lines: list[str] = []
    for index, word in enumerate(words):
        pc = start_pc + index * 4
        text = isa.disassemble_word(word, pc)
        prefix: list[str] = []
        if show_addresses:
            prefix.append(f"{pc:08x}")
        if show_words:
            prefix.append(f"{word & 0xFFFFFFFF:08x}")
        lines.append(("  ".join(prefix) + "  " if prefix else "") + text)
    return "\n".join(lines)


def disassemble_file(path: Path, *, input_format: str = "auto",
                     start_pc: int = 0, show_words: bool = True,
                     show_addresses: bool = True) -> str:
    return disassemble_words(
        read_words(path, input_format),
        start_pc=start_pc,
        show_words=show_words,
        show_addresses=show_addresses,
    )


def parse_int(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"entero invalido: {text}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MiniISA disassembler")
    parser.add_argument("input", type=Path, help="fichero .bin o .hex")
    parser.add_argument(
        "-f", "--format",
        choices=("auto", "bin", "hex"),
        default="auto",
        help="formato de entrada; por defecto se infiere por extension",
    )
    parser.add_argument(
        "--start-pc",
        type=parse_int,
        default=0,
        help="direccion inicial para calcular destinos relativos",
    )
    parser.add_argument(
        "--no-addresses",
        action="store_true",
        help="no mostrar la columna de direccion",
    )
    parser.add_argument(
        "--no-words",
        action="store_true",
        help="no mostrar la palabra codificada",
    )

    args = parser.parse_args(argv)

    try:
        text = disassemble_file(
            args.input,
            input_format=args.format,
            start_pc=args.start_pc,
            show_words=not args.no_words,
            show_addresses=not args.no_addresses,
        )
    except DisasmError as error:
        raise SystemExit(f"error: {error}") from None

    if text:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
