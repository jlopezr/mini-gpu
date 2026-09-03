#!/usr/bin/env python3
"""
MiniCPU functional simulator v0.1

Primera etapa:
- PC
- R0..R31
- memoria byte-addressed
- fetch/decode/execute
- MOVI, MOVHI, ORI, ADD, ADDI, SUB, HALT

Semántica:
- registros de 32 bits
- wrap módulo 2^32
- instrucciones little-endian de 32 bits
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

MASK32 = 0xFFFFFFFF


def u32(x: int) -> int:
    return x & MASK32


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    return value - (1 << bits) if value & sign else value


class CPU:
    def __init__(self, memory_size: int = 1024 * 1024):
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
        end = address + len(data)
        if end > len(self.memory):
            raise ValueError("programa demasiado grande para la memoria")
        self.memory[address:end] = data
        self.pc = address

    def read_u32(self, address: int) -> int:
        if address < 0 or address + 4 > len(self.memory):
            raise RuntimeError(f"lectura fuera de memoria: 0x{address:08X}")
        if address & 3:
            raise RuntimeError(f"lectura no alineada: 0x{address:08X}")
        return struct.unpack_from("<I", self.memory, address)[0]

    def fetch(self) -> int:
        return self.read_u32(self.pc)

    def step(self) -> None:
        if self.halted:
            return

        instr = self.fetch()
        opcode = (instr >> 26) & 0x3F

        # Avanzamos PC por defecto. Los branches futuros lo sustituirán.
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

        elif opcode == 0x3F:  # HALT
            self.halted = True

        else:
            raise RuntimeError(
                f"opcode no implementado 0x{opcode:02X} "
                f"en PC=0x{u32(self.pc - 4):08X}"
            )

        self.instructions_executed += 1

    def run(self, max_instructions: int = 1_000_000) -> None:
        while not self.halted:
            if self.instructions_executed >= max_instructions:
                raise RuntimeError("límite de instrucciones alcanzado")
            self.step()


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniCPU functional simulator v0.1")
    parser.add_argument("program", type=Path)
    parser.add_argument("--max", type=int, default=1_000_000)
    args = parser.parse_args()

    cpu = CPU()
    cpu.load_program(args.program.read_bytes())
    cpu.run(args.max)

    print(f"HALT tras {cpu.instructions_executed} instrucciones")
    print(f"PC = 0x{cpu.pc:08X}")
    for i, value in enumerate(cpu.regs):
        if value != 0:
            print(f"R{i:02d} = 0x{value:08X} ({value})")


if __name__ == "__main__":
    main()
