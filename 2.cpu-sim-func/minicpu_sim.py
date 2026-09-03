#!/usr/bin/env python3
"""
MiniCPU functional simulator v0.1

Implementa:

- PC
- R0..R31
- memoria byte-addressed
- fetch/decode/execute
- MOVI, MOVHI, ORI, ADD, ADDI, SUB
- MUL, MULFX, DIV
- LOAD, STORE
- BEQ, BNE, BLT, BGE, BLTU, BGEU, BRA
- HALT

Semántica:

- registros de 32 bits
- wrap módulo 2^32
- instrucciones y memoria little-endian
- LOAD/STORE de words alineadas a 4 bytes
- MUL devuelve los 32 bits bajos del producto
- MULFX usa operandos signed Q16.16
- DIV es signed y trunca hacia cero
- branches relativos a PC+4, en unidades de instrucción
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

MASK32 = 0xFFFFFFFF


def u32(x: int) -> int:
    """Conserva únicamente los 32 bits bajos."""
    return x & MASK32


def s32(x: int) -> int:
    """Interpreta un patrón de 32 bits como entero signed."""
    x &= MASK32
    return x - (1 << 32) if x & 0x80000000 else x


def sign_extend(value: int, bits: int) -> int:
    """Extiende el signo de un entero codificado con 'bits' bits."""
    sign = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    return value - (1 << bits) if value & sign else value


def signed_divide(a: int, b: int) -> int:
    """Divide enteros signed truncando el resultado hacia cero."""
    if b == 0:
        raise RuntimeError("división por cero")

    # Evitamos int(a / b): pasaría por float y podría perder precisión.
    quotient = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        quotient = -quotient
    return quotient


class CPU:
    def __init__(self, memory_size: int = 2 * 1024 * 1024):
        self.regs = [0] * 32
        self.pc = 0
        self.memory = bytearray(memory_size)
        self.halted = False
        self.instructions_executed = 0

    def reset(self) -> None:
        self.regs = [0] * 32
        self.pc = 0
        self.halted = False
        self.instructions_executed = 0

    def load_program(self, data: bytes, address: int = 0) -> None:
        if address & 3:
            raise ValueError("dirección de carga no alineada")
        if len(data) & 3:
            raise ValueError("el programa no contiene instrucciones completas")

        end = address + len(data)
        if address < 0 or end > len(self.memory):
            raise ValueError("programa demasiado grande para la memoria")

        self.memory[address:end] = data
        self.pc = address
        self.halted = False

    def read_u32(self, address: int) -> int:
        if address < 0 or address + 4 > len(self.memory):
            raise RuntimeError(f"lectura fuera de memoria: 0x{address:08X}")
        if address & 3:
            raise RuntimeError(f"lectura no alineada: 0x{address:08X}")
        return struct.unpack_from("<I", self.memory, address)[0]

    def write_u32(self, address: int, value: int) -> None:
        if address < 0 or address + 4 > len(self.memory):
            raise RuntimeError(f"escritura fuera de memoria: 0x{address:08X}")
        if address & 3:
            raise RuntimeError(f"escritura no alineada: 0x{address:08X}")
        struct.pack_into("<I", self.memory, address, u32(value))

    def fetch(self) -> int:
        return self.read_u32(self.pc)

    def step(self) -> None:
        if self.halted:
            return

        instr = self.fetch()
        opcode = (instr >> 26) & 0x3F

        # Avanzamos PC por defecto. Como los branches suman su offset después,
        # su dirección base es PC+4.
        instr_pc = self.pc
        self.pc = u32(self.pc + 4)

        if opcode == 0x10:  # MOVI
            rd = (instr >> 21) & 0x1F
            imm16 = instr & 0xFFFF
            self.regs[rd] = u32(sign_extend(imm16, 16))

        elif opcode == 0x17:  # MOVHI
            rd = (instr >> 21) & 0x1F
            imm16 = instr & 0xFFFF
            self.regs[rd] = u32(imm16 << 16)

        elif opcode == 0x13:  # ORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            self.regs[rd] = u32(self.regs[ra] | imm16)

        elif opcode == 0x01:  # ADD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.regs[rd] = u32(self.regs[ra] + self.regs[rb])

        elif opcode == 0x11:  # ADDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            self.regs[rd] = u32(self.regs[ra] + imm16)

        elif opcode == 0x02:  # SUB
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.regs[rd] = u32(self.regs[ra] - self.regs[rb])

        elif opcode == 0x0A:  # MUL
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Producto 32 x 32; conservamos los 32 bits bajos.
            self.regs[rd] = u32(self.regs[ra] * self.regs[rb])

        elif opcode == 0x03:  # MULFX signed Q16.16
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Q16.16 x Q16.16 produce Q32.32. El desplazamiento aritmético
            # restaura la escala Q16.16 antes del wrap final a 32 bits.
            product = s32(self.regs[ra]) * s32(self.regs[rb])
            self.regs[rd] = u32(product >> 16)

        elif opcode == 0x0C:  # DIV signed
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            dividend = s32(self.regs[ra])
            divisor = s32(self.regs[rb])
            self.regs[rd] = u32(signed_divide(dividend, divisor))

        elif opcode == 0x15:  # LOAD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(self.regs[ra] + imm16)
            self.regs[rd] = self.read_u32(address)

        elif opcode == 0x16:  # STORE
            # En STORE, el campo Rd contiene el registro fuente.
            source = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(self.regs[ra] + imm16)
            self.write_u32(address, self.regs[source])

        elif opcode == 0x20:  # BEQ
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if self.regs[ra] == self.regs[rb]:
                self.pc = u32(self.pc + (imm16 << 2))

        elif opcode == 0x21:  # BNE
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if self.regs[ra] != self.regs[rb]:
                self.pc = u32(self.pc + (imm16 << 2))

        elif opcode == 0x22:  # BLT signed
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if s32(self.regs[ra]) < s32(self.regs[rb]):
                self.pc = u32(self.pc + (imm16 << 2))

        elif opcode == 0x23:  # BGE signed
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if s32(self.regs[ra]) >= s32(self.regs[rb]):
                self.pc = u32(self.pc + (imm16 << 2))

        elif opcode == 0x24:  # BLTU unsigned
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if self.regs[ra] < self.regs[rb]:
                self.pc = u32(self.pc + (imm16 << 2))

        elif opcode == 0x25:  # BGEU unsigned
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if self.regs[ra] >= self.regs[rb]:
                self.pc = u32(self.pc + (imm16 << 2))

        elif opcode == 0x2F:  # BRA
            # BRA dispone de un offset signed de 26 bits porque no usa
            # registros. El offset también está expresado en instrucciones.
            offset26 = sign_extend(instr & 0x03FFFFFF, 26)
            self.pc = u32(self.pc + (offset26 << 2))

        elif opcode == 0x3F:  # HALT
            self.halted = True

        else:
            raise RuntimeError(
                f"opcode no implementado 0x{opcode:02X} "
                f"en PC=0x{instr_pc:08X}"
            )

        self.instructions_executed += 1

    def run(self, max_instructions: int = 100_000_000) -> None:
        while not self.halted:
            if self.instructions_executed >= max_instructions:
                raise RuntimeError(
                    f"límite de instrucciones alcanzado "
                    f"en PC=0x{self.pc:08X}"
                )
            self.step()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MiniCPU functional simulator v0.1"
    )
    parser.add_argument("program", type=Path)
    parser.add_argument("--max", type=int, default=100_000_000)
    parser.add_argument(
        "--memory-size",
        type=lambda value: int(value, 0),
        default=2 * 1024 * 1024,
        help="tamaño de memoria en bytes (admite 0x...)",
    )
    args = parser.parse_args()

    cpu = CPU(args.memory_size)
    cpu.load_program(args.program.read_bytes())
    cpu.run(args.max)

    print(f"HALT tras {cpu.instructions_executed} instrucciones")
    print(f"PC = 0x{cpu.pc:08X}")
    for i, value in enumerate(cpu.regs):
        if value != 0:
            print(f"R{i:02d} = 0x{value:08X} ({value})")


if __name__ == "__main__":
    main()
