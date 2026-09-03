#!/usr/bin/env python3
"""Simulador funcional de MiniCPU para MiniISA v0.1.

Implementa todas las instrucciones actualmente definidas y el estado
arquitectónico de error:

- Sistema: NOP, GETTID y HALT.
- ALU: ADD, SUB, AND, OR, XOR, SHL, SHR y SAR.
- Aritmética: MUL, MULFX y DIV.
- Inmediatas: MOVI, MOVHI, ADDI, ANDI, ORI y XORI.
- Memoria: LOAD y STORE.
- Control: BEQ, BNE, BLT, BGE, BLTU, BGEU y BRA.

El estado consta de PC y 32 registros generales de 32 bits; R0 también es
escribible. Las operaciones hacen wrap módulo 2**32, los binarios son
little-endian y los branches son relativos a PC+4 con offsets expresados en
palabras de 32 bits.

Este modelo utiliza una memoria unificada y byte-addressed de 32 MiB por defecto.
La implementación FPGA, en cambio, tiene espacios Harvard separados de 16 KiB
para programa y datos. Esta diferencia es deliberada: los programas deben evitar
que sus datos se solapen con el código y respetar los límites físicos cuando se
destinen a la FPGA.

Los errores detienen la CPU y conservan código y PC de la instrucción que los
provocó. No existen vectores de excepción ni reanudación.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

MASK32 = 0xFFFFFFFF
ERROR_NONE = 0x00
ERROR_INVALID_OPCODE = 0x01
ERROR_MEMORY_ACCESS = 0x02
ERROR_EXPLICIT_TRAP = 0x03
ERROR_DIVISION_BY_ZERO = 0x04
ERROR_INVALID_ENCODING = 0x05


def valid_encoding(instr: int, opcode: int) -> bool:
    """Comprueba los campos reservados de instrucciones conocidas."""
    if opcode in {0x00, 0x3E, 0x3F}:  # NOP, TRAP, HALT
        return (instr & 0x03FFFFFF) == 0
    if opcode in {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0C}:
        return (instr & 0x7FF) == 0
    if opcode in {0x10, 0x17}:  # MOVI/MOVHI require Y=0
        return ((instr >> 16) & 0x1F) == 0
    if opcode == 0x30:  # GETTID requires Y=0 and imm16=0
        return (instr & 0x1FFFFF) == 0
    return True


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
    """Estado y ejecución secuencial de una MiniCPU escalar."""

    def __init__(self, memory_size: int = 32 * 1024 * 1024):
        self.regs = [0] * 32
        self.pc = 0
        self.memory = bytearray(memory_size)
        self.halted = False
        self.error = False
        self.error_code = ERROR_NONE
        self.error_pc = 0
        self.instructions_executed = 0

    def reset(self) -> None:
        """Reinicia PC, registros y contadores sin borrar la memoria."""
        self.regs = [0] * 32
        self.pc = 0
        self.halted = False
        self.error = False
        self.error_code = ERROR_NONE
        self.error_pc = 0
        self.instructions_executed = 0

    def load_program(self, data: bytes, address: int = 0) -> None:
        """Copia un binario alineado y coloca el PC en su dirección inicial."""
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
        """Lee una palabra little-endian alineada dentro de la memoria."""
        if address < 0 or address + 4 > len(self.memory):
            raise RuntimeError(f"lectura fuera de memoria: 0x{address:08X}")
        if address & 3:
            raise RuntimeError(f"lectura no alineada: 0x{address:08X}")
        return struct.unpack_from("<I", self.memory, address)[0]

    def write_u32(self, address: int, value: int) -> None:
        """Escribe los 32 bits bajos en una dirección alineada de memoria."""
        if address < 0 or address + 4 > len(self.memory):
            raise RuntimeError(f"escritura fuera de memoria: 0x{address:08X}")
        if address & 3:
            raise RuntimeError(f"escritura no alineada: 0x{address:08X}")
        struct.pack_into("<I", self.memory, address, u32(value))

    def fetch(self) -> int:
        """Obtiene la instrucción situada en el PC actual."""
        return self.read_u32(self.pc)

    def stop_with_error(self, code: int, pc: int) -> None:
        self.halted = True
        self.error = True
        self.error_code = code
        self.error_pc = u32(pc)
        self.pc = u32(pc)

    def step(self) -> None:
        """Ejecuta y contabiliza una instrucción, salvo si la CPU está parada."""
        if self.halted:
            return

        try:
            instr = self.fetch()
        except RuntimeError:
            self.stop_with_error(ERROR_MEMORY_ACCESS, self.pc)
            return
        opcode = (instr >> 26) & 0x3F

        # Avanzamos PC por defecto. Como los branches suman su offset después,
        # su dirección base es PC+4.
        instr_pc = self.pc
        self.pc = u32(self.pc + 4)

        if not valid_encoding(instr, opcode):
            self.stop_with_error(ERROR_INVALID_ENCODING, instr_pc)
            return

        if opcode == 0x00:  # NOP
            pass

        elif opcode == 0x10:  # MOVI
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

        elif opcode == 0x04:  # AND
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.regs[rd] = self.regs[ra] & self.regs[rb]

        elif opcode == 0x05:  # OR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.regs[rd] = self.regs[ra] | self.regs[rb]

        elif opcode == 0x06:  # XOR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.regs[rd] = self.regs[ra] ^ self.regs[rb]

        elif opcode == 0x07:  # SHL
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            # MiniISA usa únicamente los cinco bits bajos de la cantidad.
            self.regs[rd] = u32(self.regs[ra] << (self.regs[rb] & 0x1F))

        elif opcode == 0x08:  # SHR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.regs[rd] = self.regs[ra] >> (self.regs[rb] & 0x1F)

        elif opcode == 0x09:  # SAR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.regs[rd] = u32(s32(self.regs[ra]) >> (self.regs[rb] & 0x1F))

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
            if divisor == 0:
                self.stop_with_error(ERROR_DIVISION_BY_ZERO, instr_pc)
                return
            self.regs[rd] = u32(signed_divide(dividend, divisor))

        elif opcode == 0x12:  # ANDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            # Los inmediatos lógicos se extienden con ceros, no con signo.
            imm16 = instr & 0xFFFF
            self.regs[rd] = self.regs[ra] & imm16

        elif opcode == 0x14:  # XORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            self.regs[rd] = self.regs[ra] ^ imm16

        elif opcode == 0x15:  # LOAD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(self.regs[ra] + imm16)
            try:
                self.regs[rd] = self.read_u32(address)
            except RuntimeError:
                self.stop_with_error(ERROR_MEMORY_ACCESS, instr_pc)
                return

        elif opcode == 0x16:  # STORE
            # En STORE, el campo Rd contiene el registro fuente.
            source = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(self.regs[ra] + imm16)
            try:
                self.write_u32(address, self.regs[source])
            except RuntimeError:
                self.stop_with_error(ERROR_MEMORY_ACCESS, instr_pc)
                return

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

        elif opcode == 0x30:  # GETTID
            rd = (instr >> 21) & 0x1F
            # La MiniCPU es escalar; el ID solo variará en la futura MiniGPU.
            self.regs[rd] = 0

        elif opcode == 0x3F:  # HALT
            self.halted = True

        elif opcode == 0x3E:  # TRAP
            self.stop_with_error(ERROR_EXPLICIT_TRAP, instr_pc)
            return

        else:
            self.stop_with_error(ERROR_INVALID_OPCODE, instr_pc)
            return

        self.instructions_executed += 1

    def run(self, max_instructions: int = 100_000_000) -> None:
        """Ejecuta hasta HALT respetando un límite de seguridad."""
        while not self.halted:
            if self.instructions_executed >= max_instructions:
                raise RuntimeError(
                    f"límite de instrucciones alcanzado "
                    f"en PC=0x{self.pc:08X}"
                )
            self.step()

    def dump_memory(self, address: int, size: int, filename: Path) -> None:
        """Guarda una región de memoria exactamente como una secuencia de bytes."""
        if address < 0 or size < 0 or address + size > len(self.memory):
            raise ValueError(
                f"volcado fuera de memoria: dirección=0x{address:08X}, "
                f"tamaño={size}"
            )

        filename.write_bytes(self.memory[address:address + size])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulador funcional de MiniCPU para MiniISA v0.1"
    )
    parser.add_argument("program", type=Path)
    parser.add_argument("--max", type=int, default=100_000_000)
    parser.add_argument(
        "--memory-size",
        type=lambda value: int(value, 0),
        default=32 * 1024 * 1024,
        help="tamaño de memoria en bytes (admite 0x...)",
    )
    parser.add_argument(
        "--dump",
        nargs=3,
        metavar=("ADDRESS", "SIZE", "FILE"),
        help="vuelca una región de memoria después de ejecutar el programa",
    )
    args = parser.parse_args()

    cpu = CPU(args.memory_size)
    cpu.load_program(args.program.read_bytes())
    cpu.run(args.max)

    if cpu.error:
        print(
            f"ERROR 0x{cpu.error_code:02X} en PC=0x{cpu.error_pc:08X} "
            f"tras {cpu.instructions_executed} instrucciones"
        )
    else:
        print(f"HALT tras {cpu.instructions_executed} instrucciones")
    print(f"PC = 0x{cpu.pc:08X}")
    for i, value in enumerate(cpu.regs):
        if value != 0:
            print(f"R{i:02d} = 0x{value:08X} ({value})")

    if args.dump is not None:
        address_text, size_text, filename_text = args.dump
        address = int(address_text, 0)
        size = int(size_text, 0)
        filename = Path(filename_text)

        cpu.dump_memory(address, size, filename)
        print(
            f"Volcados {size} bytes desde 0x{address:08X} "
            f"a {filename}"
        )


if __name__ == "__main__":
    main()
