#!/usr/bin/env python3
"""
MiniISA - definición declarativa de la ISA.

Este módulo es la única fuente de verdad para:

    - opcodes
    - formatos de instrucción
    - operandos
    - codificación
    - decodificación
    - documentación

Lo consumen:

    mini-asm
    mini-dis
    mini-isa

Las instrucciones son siempre de 32 bits y se almacenan little-endian.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# ============================================================================
# Utilidades
# ============================================================================


def mask_bits(width: int) -> int:
    return (1 << width) - 1


def sign_extend(value: int, bits: int) -> int:
    value &= mask_bits(bits)
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def check_signed(value: int, bits: int, what: str = "valor") -> int:
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1

    if not lo <= value <= hi:
        raise ValueError(
            f"{what} fuera de rango signed{bits}: {value}"
        )

    return value & mask_bits(bits)


def check_unsigned(value: int, bits: int, what: str = "valor") -> int:
    hi = mask_bits(bits)

    if not 0 <= value <= hi:
        raise ValueError(
            f"{what} fuera de rango unsigned{bits}: {value}"
        )

    return value


# ============================================================================
# Campos físicos
# ============================================================================


@dataclass(frozen=True)
class Field:
    """
    Campo físico dentro de una instrucción de 32 bits.

    lsb:
        bit menos significativo.

    width:
        número de bits.
    """

    name: str
    lsb: int
    width: int

    @property
    def mask(self) -> int:
        return mask_bits(self.width) << self.lsb

    @property
    def msb(self) -> int:
        return self.lsb + self.width - 1

    def extract(self, word: int) -> int:
        return (word >> self.lsb) & mask_bits(self.width)

    def insert(self, word: int, value: int) -> int:
        if value & ~mask_bits(self.width):
            raise ValueError(
                f"{self.name}: 0x{value:x} no cabe en {self.width} bits"
            )

        word &= ~self.mask
        word |= (value & mask_bits(self.width)) << self.lsb
        return word


# Campo común

OPCODE = Field("opcode", 26, 6)


# R format
#
# 31       26 25    21 20    16 15    11 10           0
# +----------+--------+--------+--------+---------------+
# | opcode   |   rd   |   ra   |   rb   |     extra     |
# +----------+--------+--------+--------+---------------+

R_RD = Field("rd", 21, 5)
R_RA = Field("ra", 16, 5)
R_RB = Field("rb", 11, 5)
R_EXTRA = Field("extra", 0, 11)


# I format
#
# 31       26 25    21 20    16 15                    0
# +----------+--------+--------+------------------------+
# | opcode   |   x    |   y    |         imm16          |
# +----------+--------+--------+------------------------+

I_X = Field("x", 21, 5)
I_Y = Field("y", 16, 5)
I_IMM16 = Field("imm16", 0, 16)


# B format
#
# 31       26 25                                      0
# +----------+------------------------------------------+
# | opcode   |                offset26                  |
# +----------+------------------------------------------+

B_OFFSET26 = Field("offset26", 0, 26)


# ============================================================================
# Formatos
# ============================================================================


@dataclass(frozen=True)
class Format:
    name: str
    fields: tuple[Field, ...]


R = Format(
    "R",
    (
        OPCODE,
        R_RD,
        R_RA,
        R_RB,
        R_EXTRA,
    ),
)


I = Format(
    "I",
    (
        OPCODE,
        I_X,
        I_Y,
        I_IMM16,
    ),
)


B = Format(
    "B",
    (
        OPCODE,
        B_OFFSET26,
    ),
)


# ============================================================================
# Operand kinds
# ============================================================================


@dataclass(frozen=True)
class Operand:
    """
    Describe un operando visible en ensamblador.

    kind:

        reg
        simm
        uimm
        branch

    field:
        campo físico donde se almacena.

    branch:
        el valor ensamblado es un offset relativo al PC,
        expresado en palabras de 32 bits.
    """

    name: str
    field: Field
    kind: str
    bits: int | None = None

    def decode(self, word: int, pc: int = 0) -> int:
        raw = self.field.extract(word)

        if self.kind == "reg":
            return raw

        if self.kind == "simm":
            return sign_extend(raw, self.bits or self.field.width)

        if self.kind == "uimm":
            return raw

        if self.kind == "branch":
            offset = sign_extend(
                raw,
                self.bits or self.field.width,
            )
            return pc + 4 + offset * 4

        raise ValueError(
            f"tipo de operando desconocido: {self.kind}"
        )


def reg(name: str, field: Field) -> Operand:
    return Operand(name, field, "reg", field.width)


def simm(name: str, field: Field, bits: int | None = None) -> Operand:
    return Operand(
        name,
        field,
        "simm",
        bits or field.width,
    )


def uimm(name: str, field: Field, bits: int | None = None) -> Operand:
    return Operand(
        name,
        field,
        "uimm",
        bits or field.width,
    )


def branch(name: str, field: Field, bits: int | None = None) -> Operand:
    return Operand(
        name,
        field,
        "branch",
        bits or field.width,
    )


# ============================================================================
# Instrucciones
# ============================================================================


@dataclass(frozen=True)
class Instruction:
    name: str
    opcode: int
    fmt: Format
    operands: tuple[Operand, ...]

    syntax: str
    description: str

    # Bits adicionales que deben tener un valor determinado.
    #
    # Esto permite describir variantes como:
    #
    #   SHL   opcode=07, bit10=0
    #   SHLI  opcode=07, bit10=1
    #
    fixed_mask: int = 0
    fixed_value: int = 0

    category: str = ""

    @property
    def match_mask(self) -> int:
        return OPCODE.mask | self.fixed_mask

    @property
    def match_value(self) -> int:
        return (
            ((self.opcode & 0x3F) << OPCODE.lsb)
            | self.fixed_value
        )

    def matches(self, word: int) -> bool:
        return (
            word & self.match_mask
        ) == self.match_value

    def decode_operands(
        self,
        word: int,
        pc: int = 0,
    ) -> list[int]:

        return [
            operand.decode(word, pc)
            for operand in self.operands
        ]


# ============================================================================
# Helpers de declaración
# ============================================================================


def r3(
    name: str,
    opcode: int,
    description: str,
    *,
    category: str = "ALU",
) -> Instruction:

    return Instruction(
        name=name,
        opcode=opcode,
        fmt=R,
        operands=(
            reg("Rd", R_RD),
            reg("Ra", R_RA),
            reg("Rb", R_RB),
        ),
        syntax=f"{name} Rd, Ra, Rb",
        description=description,
        category=category,
    )


def i3s(
    name: str,
    opcode: int,
    description: str,
    *,
    category: str = "Immediate",
) -> Instruction:

    return Instruction(
        name=name,
        opcode=opcode,
        fmt=I,
        operands=(
            reg("Rd", I_X),
            reg("Ra", I_Y),
            simm("imm16", I_IMM16),
        ),
        syntax=f"{name} Rd, Ra, imm16",
        description=description,
        category=category,
    )


def i3u(
    name: str,
    opcode: int,
    description: str,
    *,
    category: str = "Immediate",
) -> Instruction:

    return Instruction(
        name=name,
        opcode=opcode,
        fmt=I,
        operands=(
            reg("Rd", I_X),
            reg("Ra", I_Y),
            uimm("imm16", I_IMM16),
        ),
        syntax=f"{name} Rd, Ra, imm16",
        description=description,
        category=category,
    )


def branch16(
    name: str,
    opcode: int,
    description: str,
) -> Instruction:

    return Instruction(
        name=name,
        opcode=opcode,
        fmt=I,
        operands=(
            reg("Ra", I_X),
            reg("Rb", I_Y),
            branch("target", I_IMM16),
        ),
        syntax=f"{name} Ra, Rb, target",
        description=description,
        category="Control",
    )


# ============================================================================
# ISA
# ============================================================================


SHIFT_IMMEDIATE_BIT = 1 << 10


INSTRUCTIONS: tuple[Instruction, ...] = (

    # ------------------------------------------------------------------------
    # ALU
    # ------------------------------------------------------------------------

    Instruction(
        "NOP",
        0x00,
        R,
        (),
        "NOP",
        "No operation",
        category="System",
    ),

    r3("ADD",   0x01, "Rd = Ra + Rb"),
    r3("SUB",   0x02, "Rd = Ra - Rb"),
    r3("MULFX", 0x03, "Fixed-point multiply"),
    r3("AND",   0x04, "Rd = Ra & Rb"),
    r3("OR",    0x05, "Rd = Ra | Rb"),
    r3("XOR",   0x06, "Rd = Ra ^ Rb"),

    # Los shifts de registro exigen bit10 = 0.
    #
    # De ese modo el decoder puede distinguir SHL de SHLI.

    Instruction(
        "SHL",
        0x07,
        R,
        (
            reg("Rd", R_RD),
            reg("Ra", R_RA),
            reg("Rb", R_RB),
        ),
        "SHL Rd, Ra, Rb",
        "Rd = Ra << Rb",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=0,
        category="ALU",
    ),

    Instruction(
        "SHR",
        0x08,
        R,
        (
            reg("Rd", R_RD),
            reg("Ra", R_RA),
            reg("Rb", R_RB),
        ),
        "SHR Rd, Ra, Rb",
        "Logical shift right",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=0,
        category="ALU",
    ),

    Instruction(
        "SAR",
        0x09,
        R,
        (
            reg("Rd", R_RD),
            reg("Ra", R_RA),
            reg("Rb", R_RB),
        ),
        "SAR Rd, Ra, Rb",
        "Arithmetic shift right",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=0,
        category="ALU",
    ),

    # Shift inmediato.
    #
    # El imm5 ocupa físicamente el campo Rb.
    # bit10 indica la variante inmediata.

    Instruction(
        "SHLI",
        0x07,
        R,
        (
            reg("Rd", R_RD),
            reg("Ra", R_RA),
            uimm("imm5", R_RB, 5),
        ),
        "SHLI Rd, Ra, imm5",
        "Rd = Ra << imm5",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=SHIFT_IMMEDIATE_BIT,
        category="ALU",
    ),

    Instruction(
        "SHRI",
        0x08,
        R,
        (
            reg("Rd", R_RD),
            reg("Ra", R_RA),
            uimm("imm5", R_RB, 5),
        ),
        "SHRI Rd, Ra, imm5",
        "Logical shift right immediate",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=SHIFT_IMMEDIATE_BIT,
        category="ALU",
    ),

    Instruction(
        "SARI",
        0x09,
        R,
        (
            reg("Rd", R_RD),
            reg("Ra", R_RA),
            uimm("imm5", R_RB, 5),
        ),
        "SARI Rd, Ra, imm5",
        "Arithmetic shift right immediate",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=SHIFT_IMMEDIATE_BIT,
        category="ALU",
    ),

    r3("MUL",   0x0A, "Low 32 bits of signed multiply"),
    r3("MULHI", 0x0B, "High 32 bits of signed multiply"),
    r3("DIV",   0x0C, "Signed division"),
    r3("DIVU",  0x0D, "Unsigned division"),
    r3("REM",   0x0E, "Signed remainder"),
    r3("REMU",  0x0F, "Unsigned remainder"),

    # ------------------------------------------------------------------------
    # Immediate
    # ------------------------------------------------------------------------

    Instruction(
        "MOVI",
        0x10,
        I,
        (
            reg("Rd", I_X),
            simm("imm16", I_IMM16),
        ),
        "MOVI Rd, imm16",
        "Rd = sign_extend(imm16)",
        category="Immediate",
    ),

    i3s(
        "ADDI",
        0x11,
        "Rd = Ra + sign_extend(imm16)",
    ),

    i3u(
        "ANDI",
        0x12,
        "Rd = Ra & imm16",
    ),

    i3u(
        "ORI",
        0x13,
        "Rd = Ra | imm16",
    ),

    i3u(
        "XORI",
        0x14,
        "Rd = Ra ^ imm16",
    ),

    # ------------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------------

    i3s(
        "LOAD",
        0x15,
        "Rd = mem32[Ra + sign_extend(imm16)]",
        category="Memory",
    ),

    i3s(
        "STORE",
        0x16,
        "mem32[Ra + sign_extend(imm16)] = Rd",
        category="Memory",
    ),

    Instruction(
        "MOVHI",
        0x17,
        I,
        (
            reg("Rd", I_X),
            uimm("imm16", I_IMM16),
        ),
        "MOVHI Rd, imm16",
        "Rd = imm16 << 16",
        category="Immediate",
    ),

    i3s(
        "LOADB",
        0x18,
        "Rd = sign_extend(mem8[Ra + sign_extend(imm16)])",
        category="Memory",
    ),

    i3s(
        "LOADUB",
        0x19,
        "Rd = zero_extend(mem8[Ra + sign_extend(imm16)])",
        category="Memory",
    ),

    i3s(
        "STOREB",
        0x1A,
        "mem8[Ra + sign_extend(imm16)] = Rd[7:0]",
        category="Memory",
    ),

    i3s(
        "LOADH",
        0x1B,
        "Rd = sign_extend(mem16[Ra + sign_extend(imm16)])",
        category="Memory",
    ),

    i3s(
        "LOADUH",
        0x1C,
        "Rd = zero_extend(mem16[Ra + sign_extend(imm16)])",
        category="Memory",
    ),

    i3s(
        "STOREH",
        0x1D,
        "mem16[Ra + sign_extend(imm16)] = Rd[15:0]",
        category="Memory",
    ),

    # ------------------------------------------------------------------------
    # Branch
    # ------------------------------------------------------------------------

    branch16(
        "BEQ",
        0x20,
        "Branch if Ra == Rb",
    ),

    branch16(
        "BNE",
        0x21,
        "Branch if Ra != Rb",
    ),

    branch16(
        "BLT",
        0x22,
        "Branch if signed(Ra) < signed(Rb)",
    ),

    branch16(
        "BGE",
        0x23,
        "Branch if signed(Ra) >= signed(Rb)",
    ),

    branch16(
        "BLTU",
        0x24,
        "Branch if unsigned(Ra) < unsigned(Rb)",
    ),

    branch16(
        "BGEU",
        0x25,
        "Branch if unsigned(Ra) >= unsigned(Rb)",
    ),

    # ------------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------------

    r3(
        "SLT",
        0x26,
        "Rd = signed(Ra) < signed(Rb)",
        category="Compare",
    ),

    r3(
        "SLTU",
        0x27,
        "Rd = unsigned(Ra) < unsigned(Rb)",
        category="Compare",
    ),

    # ------------------------------------------------------------------------
    # Calls / jumps
    # ------------------------------------------------------------------------

    Instruction(
        "JAL",
        0x2C,
        I,
        (
            reg("Rd", I_X),
            branch("target", I_IMM16),
        ),
        "JAL Rd, target",
        "Rd = PC + 4; PC = target",
        category="Control",
    ),

    Instruction(
        "JALR",
        0x2D,
        I,
        (
            reg("Rd", I_X),
            reg("Ra", I_Y),
            simm("imm16", I_IMM16),
        ),
        "JALR Rd, Ra, imm16",
        "Rd = PC + 4; PC = Ra + sign_extend(imm16) * 4",
        category="Control",
    ),

    Instruction(
        "JR",
        0x2E,
        I,
        (
            reg("Ra", I_Y),
        ),
        "JR Ra",
        "PC = Ra",
        category="Control",
    ),

    Instruction(
        "BRA",
        0x2F,
        B,
        (
            branch("target", B_OFFSET26),
        ),
        "BRA target",
        "Unconditional PC-relative branch",
        category="Control",
    ),

    # ------------------------------------------------------------------------
    # System / SIMT
    # ------------------------------------------------------------------------

    Instruction(
        "GETTID",
        0x30,
        I,
        (
            reg("Rd", I_X),
        ),
        "GETTID Rd",
        "Rd = thread ID",
        category="SIMT",
    ),

    Instruction(
        "SSY",
        0x31,
        B,
        (
            branch("target", B_OFFSET26),
        ),
        "SSY target",
        "Set SIMT synchronization/reconvergence target",
        category="SIMT",
    ),

    Instruction(
        "BAR",
        0x32,
        R,
        (),
        "BAR",
        "SIMT barrier",
        category="SIMT",
    ),

    Instruction(
        "EXIT",
        0x33,
        R,
        (),
        "EXIT",
        "Terminate current SIMT thread/lane",
        category="SIMT",
    ),

    Instruction(
        "TRAP",
        0x3E,
        R,
        (),
        "TRAP",
        "Trap",
        category="System",
    ),

    Instruction(
        "HALT",
        0x3F,
        R,
        (),
        "HALT",
        "Halt processor",
        category="System",
    ),
)


# ============================================================================
# Índices
# ============================================================================


BY_NAME: dict[str, Instruction] = {
    ins.name: ins
    for ins in INSTRUCTIONS
}


BY_OPCODE: dict[int, tuple[Instruction, ...]] = {}

for _opcode in range(64):
    matches = tuple(
        ins
        for ins in INSTRUCTIONS
        if ins.opcode == _opcode
    )

    if matches:
        BY_OPCODE[_opcode] = matches


# ============================================================================
# Lookup / decode
# ============================================================================


def instruction(name: str) -> Instruction:
    try:
        return BY_NAME[name.upper()]
    except KeyError:
        raise KeyError(
            f"instrucción MiniISA desconocida: {name}"
        ) from None


def decode(word: int) -> Instruction | None:
    """
    Devuelve la instrucción que corresponde a word.

    None significa opcode/encoding desconocido.
    """

    word &= 0xFFFFFFFF

    opcode = OPCODE.extract(word)

    candidates = BY_OPCODE.get(opcode, ())

    # Las variantes más específicas primero.
    candidates = sorted(
        candidates,
        key=lambda ins: ins.match_mask.bit_count(),
        reverse=True,
    )

    for ins in candidates:
        if ins.matches(word):
            return ins

    return None


# ============================================================================
# Formateo para mini-dis
# ============================================================================


def format_operand(
    operand: Operand,
    value: int,
) -> str:

    if operand.kind == "reg":
        return f"R{value}"

    if operand.kind == "branch":
        return f"0x{value:08X}"

    return str(value)


def disassemble_word(
    word: int,
    pc: int = 0,
) -> str:

    ins = decode(word)

    if ins is None:
        return f".word 0x{word & 0xFFFFFFFF:08X}"

    values = ins.decode_operands(word, pc)

    if not values:
        return ins.name

    args = [
        format_operand(op, value)
        for op, value in zip(ins.operands, values)
    ]

    return f"{ins.name} " + ", ".join(args)


# ============================================================================
# Markdown para mini-isa
# ============================================================================


def markdown() -> str:

    out: list[str] = []

    out.append("# MiniISA")
    out.append("")
    out.append(
        "Todas las instrucciones tienen 32 bits."
    )
    out.append("")

    categories: list[str] = []

    for ins in INSTRUCTIONS:
        if ins.category not in categories:
            categories.append(ins.category)

    for category in categories:

        out.append(f"## {category}")
        out.append("")
        out.append(
            "| Opcode | Instrucción | Formato | Sintaxis | Semántica |"
        )
        out.append(
            "|---:|---|:---:|---|---|"
        )

        for ins in INSTRUCTIONS:

            if ins.category != category:
                continue

            syntax = ins.syntax.replace("|", "\\|")
            description = ins.description.replace("|", "\\|")

            out.append(
                f"| `0x{ins.opcode:02X}` "
                f"| `{ins.name}` "
                f"| {ins.fmt.name} "
                f"| `{syntax}` "
                f"| {description} |"
            )

        out.append("")

    return "\n".join(out)


# ============================================================================
# CLI mínimo: python isa.py
# ============================================================================


def main() -> int:
    print(markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())