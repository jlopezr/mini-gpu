#!/usr/bin/env python3
"""Simulador funcional de MiniCPU para MiniISA v0.1.

Implementa todas las instrucciones actualmente definidas y el estado
arquitectónico de error:

- Sistema: NOP, GETTID y HALT.
- ALU: ADD, SUB, AND, OR, XOR, SHL, SHR y SAR, estas tres con cantidad en
  registro o inmediata (SHLI/SHRI/SARI, bit 10 del encoding).
- Aritmética: MUL, MULHI, MULFX, DIV, DIVU, REM y REMU.
- Inmediatas: MOVI, MOVHI, ADDI, ANDI, ORI y XORI.
- Memoria: LOAD y STORE, y los accesos de 8 y 16 bits LOADB, LOADUB,
  STOREB, LOADH, LOADUH y STOREH.
- Control: BEQ, BNE, BLT, BGE, BLTU, BGEU y BRA.
- Comparaciones materializadas: SLT y SLTU.
- Llamadas: JAL, JALR y JR.

El estado consta de PC y 32 registros de 32 bits. **R0 está cableado a cero**:
las escrituras se descartan y las lecturas valen siempre cero. Eso convierte
`JR Ra` en `JALR R0, Ra, 0` y deja `0x2E` reclamable; `JR` sigue implementado
por compatibilidad. Las operaciones hacen wrap módulo 2**32, los binarios son
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sysid_device import (  # noqa: E402
    BIT_DIV, BIT_MUL, BIT_SUBWORD, SysIdDevice,
)

# Qué sabe ejecutar ESTE modelo, no la placa que modela.
#
# El bit SIMT queda a CERO, y no por descuido: `SSY` y `BAR` se decodifican aquí
# --tienen que hacerlo, para que el mismo binario corra en CPU y en GPU-- pero
# son `pass`. En una máquina de un solo hilo no hay divergencia que reconverger
# ni nadie con quien sincronizar. Declararlo sería prometer semántica SIMT que
# este modelo no tiene, que es justo lo que `ISA_PROFILE` existe para evitar.
#
# Un test contrasta este valor contra los opcodes que el modelo ejecuta de
# verdad, igual que se hace con el RTL.
SIMULATOR_ISA_PROFILE = BIT_MUL | BIT_DIV | BIT_SUBWORD

MASK32 = 0xFFFFFFFF
ERROR_NONE = 0x00
ERROR_INVALID_OPCODE = 0x01
ERROR_MEMORY_ACCESS = 0x02
ERROR_EXPLICIT_TRAP = 0x03
ERROR_DIVISION_BY_ZERO = 0x04
ERROR_INVALID_ENCODING = 0x05


def valid_encoding(instr: int, opcode: int) -> bool:
    """Comprueba los campos reservados de instrucciones conocidas."""
    if opcode in {0x00, 0x32, 0x3E, 0x3F}:  # NOP, BAR, TRAP, HALT
        return (instr & 0x03FFFFFF) == 0
    if opcode in {0x07, 0x08, 0x09}:  # SHL/SHR/SAR
        # El bit 10 es significativo: dice que la cantidad es inmediata
        # (propuesta-v0.2.md §4.2, opcion B). El campo reservado de estos tres
        # opcodes es por tanto `extra[9:0]`, no `extra` entero.
        return (instr & 0x3FF) == 0
    if opcode in {0x01, 0x02, 0x03, 0x04, 0x05, 0x06,
                  0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
                  0x26, 0x27}:
        return (instr & 0x7FF) == 0
    if opcode in {0x10, 0x17}:  # MOVI/MOVHI require Y=0
        return ((instr >> 16) & 0x1F) == 0
    if opcode == 0x30:  # GETTID requires Y=0 and imm16=0
        return (instr & 0x1FFFFF) == 0
    if opcode == 0x2C:  # JAL no tiene registro fuente
        return ((instr >> 16) & 0x1F) == 0
    if opcode == 0x2E:  # JR no tiene ni destino ni inmediato
        return ((instr >> 21) & 0x1F) == 0 and (instr & 0xFFFF) == 0
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


from tools.sim_devices import VideoDevice, SerialDevice


class CPU:
    """Estado y ejecución secuencial de una MiniCPU escalar."""

    def __init__(self, memory_size: int = 32 * 1024 * 1024,
                 video: "VideoDevice | None" = None,
                 serial: "SerialDevice | None" = None,
                 sysid: "SysIdDevice | None" = None):
        self.regs = [0] * 32
        self.pc = 0
        self.memory = bytearray(memory_size)
        self.halted = False
        self.error = False
        self.error_code = ERROR_NONE
        self.error_pc = 0
        self.instructions_executed = 0
        # Sin dispositivo de vídeo, 0x80000000 sigue siendo memoria fuera de
        # rango y da error, que es lo que hacían los casos de siempre.
        self.video = video
        # Igual que el video: sin dispositivo, 0x80000200 sigue siendo memoria
        # fuera de rango y da error.
        self.serial = serial
        # El bloque de identificacion. A diferencia de los otros dos, este se
        # construye SIEMPRE si no se pasa: es el unico dispositivo que toda
        # carpeta con juego de comandos tiene, asi que un programa que se
        # identifique tiene que poder probarse aqui sin montar nada.
        self.sysid = sysid if sysid is not None else SysIdDevice(
            folder=2, isa_profile=SIMULATOR_ISA_PROFILE)

    def _device(self, address: int):
        """Que dispositivo MMIO, si alguno, responde a esta direccion.

        El reparto por ventanas es el de `mmio_decoder.v`: cada dispositivo
        ocupa 256 bytes dentro de 0x80000000-0x80000FFF.
        """
        for device in (self.video, self.serial, self.sysid):
            if device is not None and device.contains(address):
                return device
        return None

    def reset(self) -> None:
        """Reinicia PC, registros y contadores sin borrar la memoria."""
        self.regs = [0] * 32
        self.pc = 0
        self.halted = False
        self.error = False
        self.error_code = ERROR_NONE
        self.error_pc = 0
        self.instructions_executed = 0

    def set_register(self, index: int, value: int) -> None:
        """Escribe un registro. R0 está cableado a cero y descarta la escritura.

        Es el único sitio del simulador que escribe el banco, igual que en el
        RTL la condición vive dentro de `register_file.v`. Las lecturas no se
        tocan: como nadie escribe la entrada 0 y el reset la deja a cero, leer
        R0 devuelve cero por construcción.
        """
        if index == 0:
            return
        self.regs[index] = value

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
        device = self._device(address)
        if device is not None:
            if address & 3:
                raise RuntimeError(f"lectura no alineada: 0x{address:08X}")
            return device.read(address - device.BASE)
        if address < 0 or address + 4 > len(self.memory):
            raise RuntimeError(f"lectura fuera de memoria: 0x{address:08X}")
        if address & 3:
            raise RuntimeError(f"lectura no alineada: 0x{address:08X}")
        return struct.unpack_from("<I", self.memory, address)[0]

    def write_u32(self, address: int, value: int) -> None:
        """Escribe los 32 bits bajos en una dirección alineada de memoria."""
        device = self._device(address)
        if device is not None:
            if address & 3:
                raise RuntimeError(f"escritura no alineada: 0x{address:08X}")
            device.write(address - device.BASE, u32(value))
            return
        if address < 0 or address + 4 > len(self.memory):
            raise RuntimeError(f"escritura fuera de memoria: 0x{address:08X}")
        if address & 3:
            raise RuntimeError(f"escritura no alineada: 0x{address:08X}")
        struct.pack_into("<I", self.memory, address, u32(value))

    def read_sub(self, address: int, size: int) -> int:
        """Lee 1 o 2 bytes little-endian. Las medias palabras exigen par."""
        if size == 2 and address & 1:
            raise RuntimeError(f"lectura no alineada: 0x{address:08X}")
        if self._device(address) is not None:
            # El espacio MMIO son registros de 32 bits: no admite accesos
            # parciales, igual que el mmio_mux del hardware.
            raise RuntimeError(f"acceso sub-palabra a MMIO: 0x{address:08X}")
        if address < 0 or address + size > len(self.memory):
            raise RuntimeError(f"lectura fuera de memoria: 0x{address:08X}")
        return int.from_bytes(self.memory[address:address + size], "little")

    def write_sub(self, address: int, size: int, value: int) -> None:
        """Escribe los 8 o 16 bits bajos de 'value' sin tocar el resto."""
        if size == 2 and address & 1:
            raise RuntimeError(f"escritura no alineada: 0x{address:08X}")
        if self._device(address) is not None:
            raise RuntimeError(f"acceso sub-palabra a MMIO: 0x{address:08X}")
        if address < 0 or address + size > len(self.memory):
            raise RuntimeError(f"escritura fuera de memoria: 0x{address:08X}")
        masked = value & ((1 << (8 * size)) - 1)
        self.memory[address:address + size] = masked.to_bytes(size, "little")

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

        if self.video is not None:
            # El reloj de frames avanza ANTES de ejecutar, para que la parada
            # por HALT_AT ocurra en el mismo sitio que en el hardware: al
            # completarse el intercambio, no una instruccion despues.
            self.video.tick()
            if self.video.halt_request:
                self.video.halt_request = False
                self.halted = True
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
            self.set_register(rd, u32(sign_extend(imm16, 16)))

        elif opcode == 0x17:  # MOVHI
            rd = (instr >> 21) & 0x1F
            imm16 = instr & 0xFFFF
            self.set_register(rd, u32(imm16 << 16))

        elif opcode == 0x13:  # ORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            self.set_register(rd, u32(self.regs[ra] | imm16))

        elif opcode == 0x01:  # ADD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.set_register(rd, u32(self.regs[ra] + self.regs[rb]))

        elif opcode == 0x11:  # ADDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            self.set_register(rd, u32(self.regs[ra] + imm16))

        elif opcode == 0x02:  # SUB
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.set_register(rd, u32(self.regs[ra] - self.regs[rb]))

        elif opcode == 0x04:  # AND
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.set_register(rd, self.regs[ra] & self.regs[rb])

        elif opcode == 0x05:  # OR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.set_register(rd, self.regs[ra] | self.regs[rb])

        elif opcode == 0x06:  # XOR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.set_register(rd, self.regs[ra] ^ self.regs[rb])

        elif opcode in (0x07, 0x08, 0x09):  # SHL / SHR / SAR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            # Opción B de propuesta-v0.2.md §4.2: el bit 10 dice que la cantidad
            # es inmediata y viaja en el propio campo Rb. MiniISA usa siempre
            # cinco bits de cantidad, así que con inmediato el campo entra tal
            # cual y con registro se enmascara.
            amount = rb if (instr >> 10) & 1 else self.regs[rb] & 0x1F
            if opcode == 0x07:
                self.set_register(rd, u32(self.regs[ra] << amount))
            elif opcode == 0x08:
                self.set_register(rd, self.regs[ra] >> amount)
            else:
                self.set_register(rd, u32(s32(self.regs[ra]) >> amount))

        elif opcode == 0x0A:  # MUL
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Producto 32 x 32; conservamos los 32 bits bajos.
            self.set_register(rd, u32(self.regs[ra] * self.regs[rb]))

        elif opcode == 0x03:  # MULFX signed Q16.16
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Q16.16 x Q16.16 produce Q32.32. El desplazamiento aritmético
            # restaura la escala Q16.16 antes del wrap final a 32 bits.
            product = s32(self.regs[ra]) * s32(self.regs[rb])
            self.set_register(rd, u32(product >> 16))

        elif opcode == 0x0B:  # MULHI, parte alta SIGNED
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Decisión documentada en 1.isa/isa.md §3: MULHI es con signo, como
            # MULH de RISC-V. `MUL` da los 32 bits bajos y `MULHI` los altos del
            # MISMO producto signed de 64 bits.
            product = s32(self.regs[ra]) * s32(self.regs[rb])
            self.set_register(rd, u32(product >> 32))

        elif opcode in (0x0C, 0x0D, 0x0E, 0x0F):  # DIV / DIVU / REM / REMU
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            is_signed = opcode in (0x0C, 0x0E)
            dividend = s32(self.regs[ra]) if is_signed else self.regs[ra]
            divisor = s32(self.regs[rb]) if is_signed else self.regs[rb]
            if divisor == 0:
                self.stop_with_error(ERROR_DIVISION_BY_ZERO, instr_pc)
                return

            if opcode in (0x0C, 0x0D):
                quotient = (signed_divide(dividend, divisor) if is_signed
                            else dividend // divisor)
                self.set_register(rd, u32(quotient))
            else:
                # El resto acompaña a una división truncada hacia cero, así que
                # toma el signo del DIVIDENDO: rem = a - (a/b)*b.
                if is_signed:
                    remainder = dividend - signed_divide(dividend, divisor) * divisor
                else:
                    remainder = dividend % divisor
                self.set_register(rd, u32(remainder))

        elif opcode == 0x12:  # ANDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            # Los inmediatos lógicos se extienden con ceros, no con signo.
            imm16 = instr & 0xFFFF
            self.set_register(rd, self.regs[ra] & imm16)

        elif opcode == 0x14:  # XORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            self.set_register(rd, self.regs[ra] ^ imm16)

        elif opcode == 0x15:  # LOAD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(self.regs[ra] + imm16)
            try:
                self.set_register(rd, self.read_u32(address))
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

        elif opcode in (0x18, 0x19, 0x1B, 0x1C):  # LOADB/LOADUB/LOADH/LOADUH
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            size = 1 if opcode in (0x18, 0x19) else 2
            is_signed = opcode in (0x18, 0x1B)

            address = u32(self.regs[ra] + imm16)
            try:
                raw = self.read_sub(address, size)
            except RuntimeError:
                self.stop_with_error(ERROR_MEMORY_ACCESS, instr_pc)
                return
            self.set_register(rd, u32(sign_extend(raw, 8 * size)) if is_signed else raw)

        elif opcode in (0x1A, 0x1D):  # STOREB / STOREH
            # Como en STORE, el campo Rd contiene el registro fuente.
            source = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            size = 1 if opcode == 0x1A else 2

            address = u32(self.regs[ra] + imm16)
            try:
                self.write_sub(address, size, self.regs[source])
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

        elif opcode == 0x26:  # SLT, comparacion materializada con signo
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.set_register(rd, 1 if s32(self.regs[ra]) < s32(self.regs[rb]) else 0)

        elif opcode == 0x27:  # SLTU, comparacion materializada sin signo
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            self.set_register(rd, 1 if self.regs[ra] < self.regs[rb] else 0)

        elif opcode == 0x2C:  # JAL
            # El enlace es PC+4, que ya está en self.pc: el fetch lo adelantó.
            # El offset, como el de los branches, cuenta palabras.
            rd = (instr >> 21) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            link = self.pc
            self.pc = u32(self.pc + (imm16 << 2))
            self.set_register(rd, link)

        elif opcode == 0x2D:  # JALR
            # El destino sale de un registro, así que puede venir desalineado.
            # Se descartan los dos bits bajos, igual que hace el RTL: no hay
            # ruta de error para esto.
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            link = self.pc
            self.pc = u32(self.regs[ra] + (imm16 << 2)) & ~3
            self.set_register(rd, link)

        elif opcode == 0x2E:  # JR
            # Sin enlace. R0 sigue siendo un registro general en esta ISA, así
            # que JR no puede ser el alias `JALR R0, Ra, 0` que propone v0.3.
            ra = (instr >> 16) & 0x1F
            self.pc = u32(self.regs[ra]) & ~3

        elif opcode == 0x2F:  # BRA
            # BRA dispone de un offset signed de 26 bits porque no usa
            # registros. El offset también está expresado en instrucciones.
            offset26 = sign_extend(instr & 0x03FFFFFF, 26)
            self.pc = u32(self.pc + (offset26 << 2))

        elif opcode == 0x30:  # GETTID
            rd = (instr >> 21) & 0x1F
            # La MiniCPU es escalar; el ID solo variará en la futura MiniGPU.
            self.set_register(rd, 0)

        elif opcode in (0x31, 0x32):  # SSY, BAR
            # Existen para que el MISMO binario corra en CPU y en GPU. En una
            # máquina de un solo hilo no significan nada: no hay divergencia que
            # reconverger ni nadie con quien sincronizar. No se pueden quitar del
            # fuente compartido porque en la GPU un salto divergente sin SSY
            # delante para el SM con ERROR_SIMT. Mismo criterio que GETTID.
            pass

        elif opcode == 0x3F:  # HALT
            self.halted = True

        elif opcode == 0x3E:  # TRAP
            self.stop_with_error(ERROR_EXPLICIT_TRAP, instr_pc)
            return

        else:
            self.stop_with_error(ERROR_INVALID_OPCODE, instr_pc)
            return

        self.instructions_executed += 1
        if self.serial is not None:
            self.serial.tick()

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


def load_program_file(path: Path) -> bytes:
    """Acepta .asm, .bin o .hex. Misma funcion que usan minigpu_sim.py y
    minigpu_cycle.py: vive en 1.isa/mini_asm.py para que los tres carguen
    igual y `cpusim programa.asm` signifique lo mismo que `gpusim programa.asm`.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1.isa"))
    from mini_asm import load_program_bytes

    return load_program_bytes(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulador funcional de MiniCPU para MiniISA v0.1"
    )
    parser.add_argument("program", type=Path, help=".asm, .bin o .hex")
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
    from tools import sim_peripherals
    sim_peripherals.add_arguments(parser)
    args = parser.parse_args()

    try:
        cpu = CPU(args.memory_size, **sim_peripherals.from_arguments(args))
        program = load_program_file(args.program)
    except (ValueError, OSError) as exc:
        # Una entrada mala no es un fallo del simulador, asi que no sale como
        # traceback. AsmError hereda de ValueError y cae aqui con linea y motivo.
        print(f"Simulador: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    cpu.load_program(program)
    cpu.run(args.max)
    sim_peripherals.write_outputs(args, cpu)

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
