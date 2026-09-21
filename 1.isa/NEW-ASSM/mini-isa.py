#!/usr/bin/env python3
"""
mini-isa - Generador de documentación de MiniISA.

La definición de la arquitectura vive exclusivamente en isa.py.

Ejemplos:

    python mini-isa.py

    python mini-isa.py -o miniisa.md

    python mini-isa.py --instruction LOAD

    python mini-isa.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from isa import (
    INSTRUCTIONS,
    instruction,
    markdown,
)


# ============================================================================
# Markdown de una sola instrucción
# ============================================================================


def instruction_markdown(name: str) -> str:
    """
    Genera documentación Markdown para una sola instrucción.
    """

    try:
        ins = instruction(name)
    except KeyError:
        raise ValueError(
            f"instrucción MiniISA desconocida: {name}"
        ) from None

    lines: list[str] = []

    lines.append(f"# {ins.name}")
    lines.append("")
    lines.append(f"**Opcode:** `0x{ins.opcode:02X}`")
    lines.append("")
    lines.append(f"**Formato:** `{ins.fmt.name}`")
    lines.append("")
    lines.append("**Sintaxis:**")
    lines.append("")
    lines.append("```asm")
    lines.append(ins.syntax)
    lines.append("```")
    lines.append("")
    lines.append("**Semántica:**")
    lines.append("")
    lines.append(ins.description)
    lines.append("")

    # Encoding físico
    lines.append("## Encoding")
    lines.append("")

    lines.append(
        "| Campo | Bits | Ancho |"
    )
    lines.append(
        "|---|---:|---:|"
    )

    for field in ins.fmt.fields:

        if field.msb == field.lsb:
            bits = str(field.lsb)
        else:
            bits = f"{field.msb}:{field.lsb}"

        lines.append(
            f"| `{field.name}` "
            f"| `{bits}` "
            f"| {field.width} |"
        )

    lines.append("")

    # Operandos
    if ins.operands:

        lines.append("## Operandos")
        lines.append("")

        lines.append(
            "| Operando | Tipo | Campo | Bits |"
        )
        lines.append(
            "|---|---|---|---:|"
        )

        for operand in ins.operands:

            lines.append(
                f"| `{operand.name}` "
                f"| `{operand.kind}` "
                f"| `{operand.field.name}` "
                f"| {operand.bits or operand.field.width} |"
            )

        lines.append("")

    # Bits fijos adicionales, por ejemplo SHLI.
    if ins.fixed_mask:

        lines.append("## Bits fijos")
        lines.append("")
        lines.append(
            f"- Mask: `0x{ins.fixed_mask:08X}`"
        )
        lines.append(
            f"- Value: `0x{ins.fixed_value:08X}`"
        )
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Lista corta
# ============================================================================


def instruction_list() -> str:
    """
    Lista compacta útil para terminal.
    """

    lines: list[str] = []

    for ins in INSTRUCTIONS:
        lines.append(
            f"{ins.name:<8} "
            f"0x{ins.opcode:02X}  "
            f"{ins.syntax}"
        )

    return "\n".join(lines)


# ============================================================================
# Salida
# ============================================================================


def write_output(
    text: str,
    output: Path | None,
) -> None:

    if output is None:
        print(text)
        return

    try:
        output.write_text(
            text,
            encoding="utf-8",
        )

    except OSError as error:
        raise ValueError(
            f"no se puede escribir {output}: {error}"
        ) from None


# ============================================================================
# CLI
# ============================================================================


def main(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(
        prog="mini-isa",
        description=(
            "Documentación de la arquitectura MiniISA "
            "generada desde isa.py"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="escribir la salida en un fichero",
    )

    parser.add_argument(
        "-i",
        "--instruction",
        metavar="NAME",
        help="documentar solamente una instrucción",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="mostrar una lista compacta de instrucciones",
    )

    args = parser.parse_args(argv)

    try:

        if args.list and args.instruction:
            raise ValueError(
                "--list y --instruction no se pueden usar juntos"
            )

        if args.list:
            text = instruction_list()

        elif args.instruction:
            text = instruction_markdown(
                args.instruction
            )

        else:
            text = markdown()

        write_output(
            text,
            args.output,
        )

    except ValueError as error:

        print(
            f"mini-isa: error: {error}",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())