#!/usr/bin/env python3
"""
MiniISA assembler v0.1

Sintaxis inicial:
    ADD   R1, R2, R3
    ADDI  R1, R2, -4
    MOVI  R1, 123
    MOVHI R1, 0x1234
    LOAD  R1, R2, 16
    STORE R1, R2, 16

    BEQ   R1, R2, label
    BLT   R1, R2, label
    BRA   label

    GETTID R1
    NOP
    HALT

Comentarios:
    ; comentario
    # comentario

Labels:
    loop:
        ...
        BRA loop

Salida:
    binario little-endian, una palabra de 32 bits por instrucción.
"""

from __future__ import annotations

import argparse
import re
import struct
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# ISA
# ---------------------------------------------------------------------------

OPCODES = {
    # ALU
    "NOP":    0x00,
    "ADD":    0x01,
    "SUB":    0x02,
    "MULFX":  0x03,
    "AND":    0x04,
    "OR":     0x05,
    "XOR":    0x06,
    "SHL":    0x07,
    "SHR":    0x08,
    "SAR":    0x09,
    "MUL":    0x0A,
    "MULHI":  0x0B,
    "DIV":    0x0C,
    "DIVU":   0x0D,
    "REM":    0x0E,
    "REMU":   0x0F,

    # Immediate / memory
    "MOVI":   0x10,
    "ADDI":   0x11,
    "ANDI":   0x12,
    "ORI":    0x13,
    "XORI":   0x14,
    "LOAD":   0x15,
    "STORE":  0x16,
    "MOVHI":  0x17,

    # Control
    "BEQ":    0x20,
    "BNE":    0x21,
    "BLT":    0x22,
    "BGE":    0x23,
    "BLTU":   0x24,
    "BGEU":   0x25,
    "BRA":    0x2F,

    # System / SIMT
    "GETTID": 0x30,
    "TRAP":   0x3E,
    "HALT":   0x3F,
}


R3_OPS = {
    "ADD", "SUB", "MULFX", "AND", "OR", "XOR",
    "SHL", "SHR", "SAR",
    "MUL", "MULHI", "DIV", "DIVU", "REM", "REMU",
}

I3_SIGNED_OPS = {
    "ADDI", "LOAD", "STORE",
}

I3_UNSIGNED_OPS = {
    "ANDI", "ORI", "XORI",
}

BRANCH_OPS = {
    "BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

REGISTER_RE = re.compile(r"^[Rr](\d+)$")
LABEL_RE = re.compile(r"^[A-Za-z_.$][A-Za-z0-9_.$]*$")


class AsmError(Exception):
    pass


@dataclass
class SourceLine:
    number: int
    text: str
    pc: int


def strip_comment(line: str) -> str:
    cut = len(line)
    for marker in (";", "#"):
        pos = line.find(marker)
        if pos != -1:
            cut = min(cut, pos)
    return line[:cut].strip()


def split_operands(s: str) -> list[str]:
    if not s.strip():
        return []
    return [x.strip() for x in s.split(",")]


def parse_reg(token: str) -> int:
    m = REGISTER_RE.match(token)
    if not m:
        raise AsmError(f"registro inválido: {token}")
    value = int(m.group(1))
    if not 0 <= value <= 31:
        raise AsmError(f"registro fuera de rango: {token}")
    return value


def parse_int(token: str) -> int:
    try:
        return int(token, 0)
    except ValueError:
        raise AsmError(f"entero inválido: {token}") from None


def check_signed(value: int, bits: int, what: str) -> int:
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    if not lo <= value <= hi:
        raise AsmError(f"{what} fuera de rango signed{bits}: {value}")
    return value & ((1 << bits) - 1)


def check_unsigned(value: int, bits: int, what: str) -> int:
    hi = (1 << bits) - 1
    if not 0 <= value <= hi:
        raise AsmError(f"{what} fuera de rango unsigned{bits}: {value}")
    return value


def encode_r(opcode: int, rd: int = 0, ra: int = 0, rb: int = 0, extra: int = 0) -> int:
    return (
        ((opcode & 0x3F) << 26)
        | ((rd & 0x1F) << 21)
        | ((ra & 0x1F) << 16)
        | ((rb & 0x1F) << 11)
        | (extra & 0x7FF)
    )


def encode_i(opcode: int, x: int = 0, y: int = 0, imm16: int = 0) -> int:
    return (
        ((opcode & 0x3F) << 26)
        | ((x & 0x1F) << 21)
        | ((y & 0x1F) << 16)
        | (imm16 & 0xFFFF)
    )


def encode_b(opcode: int, offset26: int = 0) -> int:
    return ((opcode & 0x3F) << 26) | (offset26 & 0x03FFFFFF)


# ---------------------------------------------------------------------------
# Pass 1
# ---------------------------------------------------------------------------

def first_pass(source: str) -> tuple[list[SourceLine], dict[str, int]]:
    labels: dict[str, int] = {}
    lines: list[SourceLine] = []
    pc = 0

    for number, raw in enumerate(source.splitlines(), 1):
        text = strip_comment(raw)
        if not text:
            continue

        # Permitimos:
        #   label:
        #   label: ADD R1,R2,R3
        while ":" in text:
            lhs, rhs = text.split(":", 1)
            label = lhs.strip()

            if not LABEL_RE.match(label):
                break

            if label in labels:
                raise AsmError(f"línea {number}: label duplicado: {label}")

            labels[label] = pc
            text = rhs.strip()

            if not text:
                break

        if not text:
            continue

        lines.append(SourceLine(number, text, pc))
        pc += 4

    return lines, labels


# ---------------------------------------------------------------------------
# Pass 2
# ---------------------------------------------------------------------------

def branch_offset(target_pc: int, current_pc: int, bits: int) -> int:
    """
    target = PC + 4 + offset * 4
    """
    delta = target_pc - (current_pc + 4)

    if delta % 4 != 0:
        raise AsmError("target de branch no alineado")

    offset = delta // 4
    return check_signed(offset, bits, "offset de branch")


def resolve_target(token: str, labels: dict[str, int]) -> int:
    if token in labels:
        return labels[token]
    return parse_int(token)


def assemble_instruction(line: SourceLine, labels: dict[str, int]) -> int:
    parts = line.text.split(None, 1)
    mnemonic = parts[0].upper()
    operand_text = parts[1] if len(parts) > 1 else ""
    ops = split_operands(operand_text)

    if mnemonic not in OPCODES:
        raise AsmError(f"instrucción desconocida: {mnemonic}")

    opcode = OPCODES[mnemonic]

    # -------------------------------------------------------
    # No operands
    # -------------------------------------------------------

    if mnemonic in {"NOP", "TRAP", "HALT"}:
        if ops:
            raise AsmError(f"{mnemonic} no acepta operandos")
        return encode_r(opcode)

    # -------------------------------------------------------
    # R-type: OP Rd, Ra, Rb
    # -------------------------------------------------------

    if mnemonic in R3_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: Rd, Ra, Rb")
        rd, ra, rb = map(parse_reg, ops)
        return encode_r(opcode, rd, ra, rb)

    # -------------------------------------------------------
    # MOVI / MOVHI
    # -------------------------------------------------------

    if mnemonic == "MOVI":
        if len(ops) != 2:
            raise AsmError("MOVI requiere: Rd, imm16")
        rd = parse_reg(ops[0])
        imm = check_signed(parse_int(ops[1]), 16, "inmediato MOVI")
        return encode_i(opcode, rd, 0, imm)

    if mnemonic == "MOVHI":
        if len(ops) != 2:
            raise AsmError("MOVHI requiere: Rd, imm16")
        rd = parse_reg(ops[0])
        imm = check_unsigned(parse_int(ops[1]), 16, "inmediato MOVHI")
        return encode_i(opcode, rd, 0, imm)

    # -------------------------------------------------------
    # I-type: OP X, Y, imm16
    # -------------------------------------------------------

    if mnemonic in I3_SIGNED_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: X, Y, imm16")
        x = parse_reg(ops[0])
        y = parse_reg(ops[1])
        imm = check_signed(parse_int(ops[2]), 16, f"inmediato {mnemonic}")
        return encode_i(opcode, x, y, imm)

    if mnemonic in I3_UNSIGNED_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: X, Y, imm16")
        x = parse_reg(ops[0])
        y = parse_reg(ops[1])
        imm = check_unsigned(parse_int(ops[2]), 16, f"inmediato {mnemonic}")
        return encode_i(opcode, x, y, imm)

    # -------------------------------------------------------
    # Conditional branches: OP Ra, Rb, label
    # -------------------------------------------------------

    if mnemonic in BRANCH_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: Ra, Rb, label")
        ra = parse_reg(ops[0])
        rb = parse_reg(ops[1])
        target_pc = resolve_target(ops[2], labels)
        off = branch_offset(target_pc, line.pc, 16)
        return encode_i(opcode, ra, rb, off)

    # -------------------------------------------------------
    # BRA label
    # -------------------------------------------------------

    if mnemonic == "BRA":
        if len(ops) != 1:
            raise AsmError("BRA requiere: label")
        target_pc = resolve_target(ops[0], labels)
        off = branch_offset(target_pc, line.pc, 26)
        return encode_b(opcode, off)

    # -------------------------------------------------------
    # GETTID Rd
    # -------------------------------------------------------

    if mnemonic == "GETTID":
        if len(ops) != 1:
            raise AsmError("GETTID requiere: Rd")
        rd = parse_reg(ops[0])
        return encode_i(opcode, rd, 0, 0)

    raise AsmError(f"{mnemonic}: encoding todavía no implementado")


def assemble(source: str) -> list[int]:
    lines, labels = first_pass(source)
    words: list[int] = []

    for line in lines:
        try:
            words.append(assemble_instruction(line, labels))
        except AsmError as e:
            raise AsmError(f"línea {line.number}: {e}\n    {line.text}") from None

    return words


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_binary(words: list[int], path: Path) -> None:
    with path.open("wb") as f:
        for word in words:
            f.write(struct.pack("<I", word))


def write_hex(words: list[int], path: Path) -> None:
    with path.open("w", encoding="ascii") as f:
        for word in words:
            f.write(f"{word:08X}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniISA assembler v0.1")
    parser.add_argument("input", type=Path, help="fichero .asm")
    parser.add_argument("-o", "--output", type=Path, help="salida .bin")
    parser.add_argument("--hex", dest="hex_output", type=Path, help="salida hexadecimal textual")
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8")

    try:
        words = assemble(source)
    except AsmError as e:
        raise SystemExit(f"error: {e}")

    output = args.output or args.input.with_suffix(".bin")
    write_binary(words, output)

    if args.hex_output:
        write_hex(words, args.hex_output)

    print(f"{len(words)} instrucciones -> {output}")


if __name__ == "__main__":
    main()
