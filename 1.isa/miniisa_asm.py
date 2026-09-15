#!/usr/bin/env python3
"""
MiniISA assembler v0.1

Sintaxis inicial:
    ADD   R1, R2, R3
    ADDI  R1, R2, -4
    MOVI  R1, 123
    MOVHI R1, 0x1234
    SHLI  R1, R2, 5     ; tambien SHRI y SARI; cantidad inmediata 0..31
    MULHI R1, R2, R3    ; parte alta signed; DIVU, REM y REMU tambien
    LOAD  R1, R2, 16
    STORE R1, R2, 16

    BEQ   R1, R2, label
    BLT   R1, R2, label
    BRA   label

    SLT   R1, R2, R3   ; comparaciones materializadas; SLTU tambien

    JAL   R31, funcion
    JALR  R31, R5, 0
    JR    R5
    RET               ; alias de JR R31

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

    # Accesos sub-palabra. Mapa de propuesta-v0.2.md §7; v0.3 reordena
    # 0x1A..0x1D, asi que estos valores cambiaran al migrar.
    "LOADB":  0x18,
    "LOADUB": 0x19,
    "STOREB": 0x1A,
    "LOADH":  0x1B,
    "LOADUH": 0x1C,
    "STOREH": 0x1D,

    # Control
    "BEQ":    0x20,
    "BNE":    0x21,
    "BLT":    0x22,
    "BGE":    0x23,
    "BLTU":   0x24,
    "BGEU":   0x25,

    # Comparaciones materializadas. R-Type, capability `compare`.
    "SLT":    0x26,
    "SLTU":   0x27,

    # Llamadas y saltos indirectos. Mapa de propuesta-v0.2.md §3.2: R0 sigue
    # siendo un registro general, asi que JR gasta opcode propio.
    "JAL":    0x2C,
    "JALR":   0x2D,
    "JR":     0x2E,

    "BRA":    0x2F,

    # System / SIMT
    "GETTID": 0x30,
    "SSY":    0x31,
    "BAR":    0x32,
    "EXIT":   0x33,
    "TRAP":   0x3E,
    "HALT":   0x3F,
}

R3_OPS = {
    "ADD", "SUB", "MULFX", "AND", "OR", "XOR",
    "SHL", "SHR", "SAR",
    "MUL", "MULHI", "DIV", "DIVU", "REM", "REMU",
    "SLT", "SLTU",
}

# Desplazamientos con cantidad inmediata: opcion B de propuesta-v0.2.md §4.2.
# No gastan opcode. Reusan el de su version con registro y encienden el bit 10
# del campo `extra`; la cantidad viaja en los cinco bits del campo Rb.
#
#   31       26 25   21 20   16 15   11 10  9         0
#   [ opcode ][  Rd  ][  Ra  ][ imm5 ][ 1 ][    0     ]
#
# Consecuencia: para 0x07..0x09 el campo reservado ya no es `extra` entero sino
# `extra[9:0]`, e `instruction[10]` pasa a ser significativo.
SHIFT_IMMEDIATE_BIT = 1 << 10

SHIFT_IMM_OPS = {
    "SHLI": "SHL",
    "SHRI": "SHR",
    "SARI": "SAR",
}

I3_SIGNED_OPS = {
    "ADDI", "LOAD", "STORE",
    "LOADB", "LOADUB", "STOREB", "LOADH", "LOADUH", "STOREH",
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
    """Quita el comentario, respetando lo que haya entre comillas.

    Las comillas importan desde que existe `.string`: un `;` o un `#` dentro
    de un mensaje son parte del mensaje, no el principio de un comentario.
    """
    dentro = False
    escapado = False
    for index, char in enumerate(line):
        if escapado:
            escapado = False
            continue
        if char == "\\" and dentro:
            escapado = True
            continue
        if char == '"':
            dentro = not dentro
            continue
        if not dentro and char in (";", "#"):
            return line[:index].strip()
    return line.strip()


# ---------------------------------------------------------------------------
# Directivas de datos
#
# El ensamblador solo sabia emitir instrucciones, asi que un programa que
# necesitara una tabla o un mensaje tenia que construirlo en tiempo de
# ejecucion a base de MOVI y STORE. Con `.word` y `.string` los datos van en la
# imagen, que es donde deben estar.
#
# La salida sigue siendo una lista de palabras de 32 bits: `.string` rellena con
# ceros hasta el multiplo de cuatro. Asi el resto de la cadena de herramientas
# --el .bin, el .hex, el cargador del monitor-- no se entera de nada.
# ---------------------------------------------------------------------------

ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", '"': '"'}


def parse_string_literal(text: str) -> bytes:
    text = text.strip()
    if len(text) < 2 or not text.startswith('"') or not text.endswith('"'):
        raise AsmError('.string requiere un literal entre comillas dobles')

    out = bytearray()
    index = 1
    end = len(text) - 1
    while index < end:
        char = text[index]
        if char == "\\":
            index += 1
            if index >= end:
                raise AsmError("escape incompleto al final de la cadena")
            if text[index] not in ESCAPES:
                raise AsmError(f"escape desconocido: \\{text[index]}")
            out += ESCAPES[text[index]].encode("latin-1")
        else:
            out += char.encode("latin-1")
        index += 1
    # NUL final: las rutinas de impresion recorren hasta el cero.
    out += b"\x00"
    while len(out) % 4:
        out += b"\x00"
    return bytes(out)


def directive_size(mnemonic: str, operand_text: str) -> int:
    """Cuantas palabras ocupa, sin resolver etiquetas.

    Hace falta en la pasada 1, donde todavia no se sabe donde esta cada
    etiqueta pero si CUANTAS palabras emite la directiva. Sin esto, toda
    etiqueta posterior a una tabla apuntaria mal.
    """
    if mnemonic == ".WORD":
        valores = split_operands(operand_text)
        if not valores:
            raise AsmError(".word requiere al menos un valor")
        return len(valores)
    if mnemonic == ".STRING":
        return len(parse_string_literal(operand_text)) // 4
    raise AsmError(f"directiva desconocida: {mnemonic}")


def directive_words(mnemonic: str, operand_text: str,
                    labels: dict[str, int]) -> list[int]:
    """Convierte una directiva en las palabras de 32 bits que emite.

    `.word` acepta etiquetas, que es lo que permite escribir una tabla de
    direcciones --un diccionario de Forth, por ejemplo-- sin calcularlas a
    mano.
    """
    if mnemonic == ".WORD":
        palabras = []
        for token in split_operands(operand_text):
            value = resolve_target(token, labels)
            if not -(1 << 31) <= value <= (1 << 32) - 1:
                raise AsmError(f".word fuera de rango de 32 bits: {value}")
            palabras.append(value & 0xFFFFFFFF)
        return palabras
    if mnemonic == ".STRING":
        data = parse_string_literal(operand_text)
        return [int.from_bytes(data[i:i + 4], "little")
                for i in range(0, len(data), 4)]
    raise AsmError(f"directiva desconocida: {mnemonic}")


def is_directive(text: str) -> bool:
    return text.split(None, 1)[0].upper() in (".WORD", ".STRING")


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
        # Una directiva ocupa lo que ocupen sus datos, no cuatro bytes. Si el
        # tamano no se calculara aqui, todas las etiquetas posteriores a una
        # tabla apuntarian mal.
        if is_directive(text):
            partes = text.split(None, 1)
            try:
                pc += 4 * directive_size(
                    partes[0].upper(), partes[1] if len(partes) > 1 else "")
            except AsmError as error:
                raise AsmError(f"línea {number}: {error}") from None
        else:
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

    # RET no es un opcode: el enlace vive en R31 por convencion de llamada.
    if mnemonic == "RET":
        if ops:
            raise AsmError("RET no acepta operandos")
        mnemonic = "JR"
        ops = ["R31"]

    # SHLI/SHRI/SARI no tienen entrada propia en OPCODES: son el mismo opcode
    # que SHL/SHR/SAR con el bit de inmediato puesto.
    if mnemonic in SHIFT_IMM_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: Rd, Ra, imm5")
        rd = parse_reg(ops[0])
        ra = parse_reg(ops[1])
        amount = parse_int(ops[2])
        if not 0 <= amount <= 31:
            raise AsmError(
                f"cantidad de {mnemonic} fuera de rango 0..31: {amount}")
        return encode_r(OPCODES[SHIFT_IMM_OPS[mnemonic]], rd, ra, amount,
                        SHIFT_IMMEDIATE_BIT)

    if mnemonic not in OPCODES:
        raise AsmError(f"instrucción desconocida: {mnemonic}")

    opcode = OPCODES[mnemonic]

    # -------------------------------------------------------
    # No operands
    # -------------------------------------------------------

    if mnemonic in {"NOP", "BAR", "EXIT", "TRAP", "HALT"}:
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
        # Admite una etiqueta, y entonces el inmediato es su DIRECCION. Es como
        # un programa carga el puntero de una tabla o de un mensaje. Solo vale
        # mientras el programa quepa en los 32 KiB que alcanza un signed16; mas
        # alla, MOVHI + ORI.
        imm = check_signed(resolve_target(ops[1], labels), 16, "inmediato MOVI")
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

    if mnemonic in {"BRA", "SSY"}:
        if len(ops) != 1:
            raise AsmError(f"{mnemonic} requiere: label")
        target_pc = resolve_target(ops[0], labels)
        off = branch_offset(target_pc, line.pc, 26)
        return encode_b(opcode, off)

    # -------------------------------------------------------
    # Llamadas y saltos indirectos
    #
    #   JAL  Rd, label      X = Rd, Y = 0,  imm16 = offset en palabras
    #   JALR Rd, Ra, imm16  X = Rd, Y = Ra, imm16 en palabras
    #   JR   Ra             X = 0,  Y = Ra, imm16 = 0
    #
    # RET es un alias de JR R31, no un opcode.
    # -------------------------------------------------------

    if mnemonic == "JAL":
        if len(ops) != 2:
            raise AsmError("JAL requiere: Rd, label")
        rd = parse_reg(ops[0])
        target_pc = resolve_target(ops[1], labels)
        off = branch_offset(target_pc, line.pc, 16)
        return encode_i(opcode, rd, 0, off)

    if mnemonic == "JALR":
        if len(ops) != 3:
            raise AsmError("JALR requiere: Rd, Ra, imm16")
        rd = parse_reg(ops[0])
        ra = parse_reg(ops[1])
        imm = check_signed(parse_int(ops[2]), 16, "inmediato JALR")
        return encode_i(opcode, rd, ra, imm)

    if mnemonic == "JR":
        if len(ops) != 1:
            raise AsmError("JR requiere: Ra")
        ra = parse_reg(ops[0])
        return encode_i(opcode, 0, ra, 0)

    # -------------------------------------------------------
    # GETTID Rd
    # -------------------------------------------------------

    if mnemonic == "GETTID":
        if len(ops) != 1:
            raise AsmError("GETTID requiere: Rd")
        rd = parse_reg(ops[0])
        return encode_i(opcode, rd, 0, 0)

    # -------------------------------------------------------
    # SSY label
    # -------------------------------------------------------

    if mnemonic == "SSY":
        if len(ops) != 1:
            raise AsmError("SSY requiere: label")
        target_pc = resolve_target(ops[0], labels)
        off = branch_offset(target_pc, line.pc, 26)
        return encode_b(opcode, off)

    raise AsmError(f"{mnemonic}: encoding todavía no implementado")

def assemble(source: str) -> list[int]:
    lines, labels = first_pass(source)
    words: list[int] = []

    for line in lines:
        try:
            if is_directive(line.text):
                partes = line.text.split(None, 1)
                words.extend(directive_words(
                    partes[0].upper(),
                    partes[1] if len(partes) > 1 else "", labels))
            else:
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
