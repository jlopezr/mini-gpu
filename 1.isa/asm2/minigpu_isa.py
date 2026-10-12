#!/usr/bin/env python3
"""
MiniISA - declarative MiniGPU ISA definition.

This module is the MiniGPU-specific source of truth: physical fields, formats,
instruction declarations, public indexes, disassembly formatting and Markdown
documentation. Generic machinery lives in isa_core.py.
"""

from __future__ import annotations

from isa_core import (
    Field,
    Format,
    ISA,
    ISAEncodingError,
    check_signed,
    check_unsigned,
    Instruction,
    Operand,
    mask_bits,
    sign_extend,
)


# Physical fields

OPCODE = Field("opcode", 26, 6)

R_RD = Field("rd", 21, 5)
R_RA = Field("ra", 16, 5)
R_RB = Field("rb", 11, 5)
R_EXTRA = Field("extra", 0, 11)

I_X = Field("x", 21, 5)
I_Y = Field("y", 16, 5)
I_IMM16 = Field("imm16", 0, 16)

B_OFFSET26 = Field("offset26", 0, 26)


# Formats

R = Format("R", (OPCODE, R_RD, R_RA, R_RB, R_EXTRA))
I = Format("I", (OPCODE, I_X, I_Y, I_IMM16))
B = Format("B", (OPCODE, B_OFFSET26))


# Operand helpers

def reg(name: str, field: Field) -> Operand:
    return Operand(name, field, "reg", field.width)


def simm(name: str, field: Field, bits: int | None = None) -> Operand:
    return Operand(name, field, "simm", bits or field.width)


def uimm(name: str, field: Field, bits: int | None = None) -> Operand:
    return Operand(name, field, "uimm", bits or field.width)


def branch(name: str, field: Field, bits: int | None = None) -> Operand:
    return Operand(
        name,
        field,
        "branch",
        bits or field.width,
        scale=4,
        pc_relative=True,
        pc_bias=4,
    )


# Declarative instruction helpers

def r3(
    name: str,
    opcode: int,
    description: str,
    *,
    category: str = "ALU",
) -> Instruction:
    return Instruction(
        name,
        opcode,
        R,
        (reg("Rd", R_RD), reg("Ra", R_RA), reg("Rb", R_RB)),
        f"{name} Rd, Ra, Rb",
        description,
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
        name,
        opcode,
        I,
        (reg("Rd", I_X), reg("Ra", I_Y), simm("imm16", I_IMM16)),
        f"{name} Rd, Ra, imm16",
        description,
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
        name,
        opcode,
        I,
        (reg("Rd", I_X), reg("Ra", I_Y), uimm("imm16", I_IMM16)),
        f"{name} Rd, Ra, imm16",
        description,
        category=category,
    )


def branch16(name: str, opcode: int, description: str) -> Instruction:
    return Instruction(
        name,
        opcode,
        I,
        (reg("Ra", I_X), reg("Rb", I_Y), branch("target", I_IMM16)),
        f"{name} Ra, Rb, target",
        description,
        category="Control",
    )


def getid(name: str, type_id: int, description: str) -> Instruction:
    return Instruction(
        name,
        0x30,
        I,
        (reg("Rd", I_X),),
        f"{name} Rd",
        description,
        fixed_mask=I_Y.mask | I_IMM16.mask,
        fixed_value=I_Y.encode(type_id),
        category="SIMT",
    )


SHIFT_IMMEDIATE_BIT = 1 << 10


INSTRUCTIONS: tuple[Instruction, ...] = (
    Instruction("NOP", 0x00, R, (), "NOP", "No operation", category="System"),
    r3("ADD", 0x01, "Rd = Ra + Rb"),
    r3("SUB", 0x02, "Rd = Ra - Rb"),
    r3("MULFX", 0x03, "Fixed-point multiply"),
    r3("AND", 0x04, "Rd = Ra & Rb"),
    r3("OR", 0x05, "Rd = Ra | Rb"),
    r3("XOR", 0x06, "Rd = Ra ^ Rb"),
    Instruction(
        "SHL",
        0x07,
        R,
        (reg("Rd", R_RD), reg("Ra", R_RA), reg("Rb", R_RB)),
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
        (reg("Rd", R_RD), reg("Ra", R_RA), reg("Rb", R_RB)),
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
        (reg("Rd", R_RD), reg("Ra", R_RA), reg("Rb", R_RB)),
        "SAR Rd, Ra, Rb",
        "Arithmetic shift right",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=0,
        category="ALU",
    ),
    Instruction(
        "SHLI",
        0x07,
        R,
        (reg("Rd", R_RD), reg("Ra", R_RA), uimm("imm5", R_RB, 5)),
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
        (reg("Rd", R_RD), reg("Ra", R_RA), uimm("imm5", R_RB, 5)),
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
        (reg("Rd", R_RD), reg("Ra", R_RA), uimm("imm5", R_RB, 5)),
        "SARI Rd, Ra, imm5",
        "Arithmetic shift right immediate",
        fixed_mask=SHIFT_IMMEDIATE_BIT,
        fixed_value=SHIFT_IMMEDIATE_BIT,
        category="ALU",
    ),
    r3("MUL", 0x0A, "Low 32 bits of signed multiply"),
    r3("MULHI", 0x0B, "High 32 bits of signed multiply"),
    r3("DIV", 0x0C, "Signed division"),
    r3("DIVU", 0x0D, "Unsigned division"),
    r3("REM", 0x0E, "Signed remainder"),
    r3("REMU", 0x0F, "Unsigned remainder"),
    Instruction(
        "MOVI",
        0x10,
        I,
        (reg("Rd", I_X), simm("imm16", I_IMM16)),
        "MOVI Rd, imm16",
        "Rd = sign_extend(imm16)",
        category="Immediate",
    ),
    i3s("ADDI", 0x11, "Rd = Ra + sign_extend(imm16)"),
    i3u("ANDI", 0x12, "Rd = Ra & imm16"),
    i3u("ORI", 0x13, "Rd = Ra | imm16"),
    i3u("XORI", 0x14, "Rd = Ra ^ imm16"),
    i3s("LOAD", 0x15, "Rd = mem32[Ra + sign_extend(imm16)]", category="Memory"),
    i3s("STORE", 0x16, "mem32[Ra + sign_extend(imm16)] = Rd", category="Memory"),
    Instruction(
        "MOVHI",
        0x17,
        I,
        (reg("Rd", I_X), uimm("imm16", I_IMM16)),
        "MOVHI Rd, imm16",
        "Rd = imm16 << 16",
        category="Immediate",
    ),
    i3s("LOADB", 0x18, "Rd = sign_extend(mem8[Ra + sign_extend(imm16)])", category="Memory"),
    i3s("LOADUB", 0x19, "Rd = zero_extend(mem8[Ra + sign_extend(imm16)])", category="Memory"),
    i3s("STOREB", 0x1A, "mem8[Ra + sign_extend(imm16)] = Rd[7:0]", category="Memory"),
    i3s("LOADH", 0x1B, "Rd = sign_extend(mem16[Ra + sign_extend(imm16)])", category="Memory"),
    i3s("LOADUH", 0x1C, "Rd = zero_extend(mem16[Ra + sign_extend(imm16)])", category="Memory"),
    i3s("STOREH", 0x1D, "mem16[Ra + sign_extend(imm16)] = Rd[15:0]", category="Memory"),
    branch16("BEQ", 0x20, "Branch if Ra == Rb"),
    branch16("BNE", 0x21, "Branch if Ra != Rb"),
    branch16("BLT", 0x22, "Branch if signed(Ra) < signed(Rb)"),
    branch16("BGE", 0x23, "Branch if signed(Ra) >= signed(Rb)"),
    branch16("BLTU", 0x24, "Branch if unsigned(Ra) < unsigned(Rb)"),
    branch16("BGEU", 0x25, "Branch if unsigned(Ra) >= unsigned(Rb)"),
    r3("SLT", 0x26, "Rd = signed(Ra) < signed(Rb)", category="Compare"),
    r3("SLTU", 0x27, "Rd = unsigned(Ra) < unsigned(Rb)", category="Compare"),
    Instruction(
        "JAL",
        0x2C,
        I,
        (reg("Rd", I_X), branch("target", I_IMM16)),
        "JAL Rd, target",
        "Rd = PC + 4; PC = target",
        category="Control",
    ),
    Instruction(
        "JALR",
        0x2D,
        I,
        (reg("Rd", I_X), reg("Ra", I_Y), simm("imm16", I_IMM16)),
        "JALR Rd, Ra, imm16",
        "Rd = PC + 4; PC = Ra + sign_extend(imm16) * 4",
        category="Control",
    ),
    Instruction(
        "JR",
        0x2E,
        I,
        (reg("Ra", I_Y),),
        "JR Ra",
        "PC = Ra",
        category="Control",
    ),
    Instruction(
        "BRA",
        0x2F,
        B,
        (branch("target", B_OFFSET26),),
        "BRA target",
        "Unconditional PC-relative branch",
        category="Control",
    ),
    getid("GETTID", 0, "Rd = thread ID"),
    getid("GETLANE", 1, "Rd = lane ID within the warp"),
    getid("GETWARP", 2, "Rd = physical warp slot"),
    getid("GETLWARP", 3, "Rd = logical warp ID"),
    getid("GETARG", 4, "Rd = warp argument pointer"),
    Instruction(
        "SSY",
        0x31,
        B,
        (branch("target", B_OFFSET26),),
        "SSY target",
        "Set SIMT synchronization/reconvergence target",
        category="SIMT",
    ),
    Instruction("BAR", 0x32, R, (), "BAR", "SIMT barrier", category="SIMT"),
    Instruction("EXIT", 0x33, R, (), "EXIT", "Terminate current SIMT thread/lane", category="SIMT"),
    Instruction("TRAP", 0x3E, R, (), "TRAP", "Trap", category="System"),
    Instruction("HALT", 0x3F, R, (), "HALT", "Halt processor", category="System"),
)


_ISA = ISA(INSTRUCTIONS)

BY_NAME: dict[str, Instruction] = dict(_ISA.by_name)
BY_OPCODE: dict[int, tuple[Instruction, ...]] = dict(_ISA.by_opcode)


def instruction(name: str) -> Instruction:
    try:
        return BY_NAME[name.upper()]
    except KeyError:
        raise KeyError(f"instruccion MiniISA desconocida: {name}") from None


def encode(name: str, **operands: int) -> int:
    return instruction(name).encode(**operands)


def decode(word: int) -> Instruction | None:
    word &= 0xFFFFFFFF
    opcode = OPCODE.extract(word)
    for candidate in BY_OPCODE.get(opcode, ()):
        if candidate.matches(word):
            return candidate
    return None


def validate_isa() -> None:
    _ISA.validate()


def format_operand(operand: Operand, value: int) -> str:
    if operand.kind == "reg":
        return f"R{value}"
    if operand.kind == "branch":
        return f"0x{value:08X}"
    return str(value)


def disassemble_word(word: int, pc: int = 0) -> str:
    ins = decode(word)
    if ins is None:
        return f".word 0x{word & 0xFFFFFFFF:08X}"

    values = ins.decode_operands(word, pc)
    if not values:
        return ins.name

    args = [
        format_operand(operand, value)
        for operand, value in zip(ins.operands, values)
    ]
    return f"{ins.name} " + ", ".join(args)


def markdown() -> str:
    out: list[str] = [
        "# MiniISA",
        "",
        "Todas las instrucciones tienen 32 bits.",
        "",
    ]

    categories: list[str] = []
    for ins in INSTRUCTIONS:
        if ins.category not in categories:
            categories.append(ins.category)

    for category in categories:
        out.append(f"## {category}")
        out.append("")
        out.append("| Opcode | Instruccion | Formato | Sintaxis | Semantica |")
        out.append("|---:|---|:---:|---|---|")

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


def main() -> int:
    print(markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
