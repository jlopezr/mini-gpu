#!/usr/bin/env python3
"""Simulador funcional de MiniGPU para MiniISA v0.1.

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

El warp controla el PC y contabiliza instrucciones completadas, incluido HALT.
Los errores detienen toda la GPU sin efectos parciales de la instrucción fallida.
Los saltos divergentes utilizan SSY y pilas separadas de regiones y caminos.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from gpu_trace import TextTrace, TraceEvent

MASK32 = 0xFFFFFFFF
MAX_WARPS = 8
MAX_SIMT_REGIONS = 8
MAX_SIMT_PATHS = 8
ERROR_NONE = 0x00
ERROR_INVALID_OPCODE = 0x01
ERROR_MEMORY_ACCESS = 0x02
ERROR_EXPLICIT_TRAP = 0x03
ERROR_DIVISION_BY_ZERO = 0x04
ERROR_INVALID_ENCODING = 0x05
ERROR_SIMT = 0x06
ERROR_BARRIER = 0x07


def valid_encoding(instr: int, opcode: int) -> bool:
    """Comprueba los campos reservados de instrucciones conocidas."""
    if opcode in {0x00, 0x32, 0x33, 0x3E, 0x3F}:  # NOP, TRAP, HALT
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
        raise ZeroDivisionError("división por cero")

    # Evitamos int(a / b): pasaría por float y podría perder precisión.
    quotient = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        quotient = -quotient
    return quotient


@dataclass(frozen=True)
class Fault:
    """Primer fallo arquitectónico; core_id=None indica fallo común del warp."""

    code: int
    pc: int
    warp_id: int
    core_id: int | None
    address: int | None = None


class ExecutionFault(Exception):
    """Fallo de la ISA, capturado exclusivamente en la frontera del warp."""

    def __init__(self, code: int, address: int | None = None):
        super().__init__(f"error 0x{code:02X}")
        self.code = code
        self.address = address


class SimulationError(RuntimeError):
    """Límite o capacidad del simulador; no es un error de la ISA."""


class InstructionLimitExceeded(SimulationError):
    pass


def check_address(memory: bytearray, address: int) -> None:
    if address < 0 or address & 3 or address + 4 > len(memory):
        raise ExecutionFault(ERROR_MEMORY_ACCESS, address)


def read_u32(memory: bytearray, address: int) -> int:
    check_address(memory, address)
    return struct.unpack_from("<I", memory, address)[0]


@dataclass
class LaneResult:
    regs: list[int]
    next_pc: int
    halted: bool
    store: tuple[int, int] | None


def config_integer(value: object, field: str) -> int:
    """Acepta enteros JSON o cadenas decimales/hexadecimales, nunca booleanos."""
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(value, 16 if value.lower().startswith('0x') else 10)
        except ValueError:
            pass
    raise ValueError(f"config: {field} debe ser un entero decimal o hexadecimal")


def config_fields(value: object, allowed: set[str], field: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"config: {field} debe ser un objeto")
    if value.keys() - allowed:
        raise ValueError(f"config: campos desconocidos en {field}")
    return value


def config_warp_size(config: object) -> int:
    config = config_fields(config, {'warp_size', 'warps'}, 'raíz')
    size = config_integer(config.get('warp_size', 8), 'warp_size')
    if size <= 0:
        raise ValueError("config: warp_size debe ser positivo")
    return size


@dataclass(frozen=True)
class SimtRegion:
    ssy_pc: int
    join_pc: int
    entry_mask: int
    path_base: int


@dataclass(frozen=True)
class SimtPath:
    pending_pc: int
    pending_mask: int


class System:
    """Memoria compartida y único registro de fallo de la GPU."""

    def __init__(self, memory_size: int = 32 * 1024 * 1024,
                 num_warps: int = 8, warp_size: int = 8, *,
                 simt_region_depth: int = MAX_SIMT_REGIONS,
                 simt_path_depth: int = MAX_SIMT_PATHS):
        if memory_size <= 0 or num_warps <= 0 or warp_size <= 0:
            raise ValueError("memoria, número de warps y tamaño de warp deben ser positivos")
        if num_warps > MAX_WARPS:
            raise ValueError("se admiten como máximo 8 warps")
        for depth in (simt_region_depth, simt_path_depth):
            if type(depth) is not int or depth <= 0:
                raise ValueError("las profundidades SIMT deben ser enteros positivos")
        self.simt_region_depth = simt_region_depth
        self.simt_path_depth = simt_path_depth
        self.memory = bytearray(memory_size)
        self.fault: Fault | None = None
        self.trace: TextTrace | None = None
        self.streaming_multiprocessor = StreamingMultiprocessor(
            self.memory, self, num_warps, warp_size
        )

    @property
    def halted(self) -> bool:
        return self.error or all(w.halted for w in self.streaming_multiprocessor.warps)

    @property
    def error(self) -> bool:
        return self.fault is not None

    @property
    def error_code(self) -> int:
        return self.fault.code if self.fault else ERROR_NONE

    @property
    def error_pc(self) -> int:
        return self.fault.pc if self.fault else 0

    @property
    def instructions_executed(self) -> int:
        return sum(w.instructions_executed for w in self.streaming_multiprocessor.warps)

    def reset(self) -> None:
        """Borra memoria in situ y deja todos los warps sin lanzar."""
        self.memory[:] = bytes(len(self.memory))
        self.fault = None
        self.streaming_multiprocessor.reset()

    def load_program(self, data: bytes, address: int = 0, *, launch: bool = True) -> None:
        """Carga memoria; por defecto lanza todos los hilos por compatibilidad."""
        if address & 3:
            raise ValueError("dirección de carga no alineada")
        if not data or len(data) & 3:
            raise ValueError("el programa debe contener instrucciones completas")
        if address < 0 or address + len(data) > len(self.memory):
            raise ValueError("programa fuera de memoria")
        self.memory[address:address + len(data)] = data
        self.fault = None
        self.streaming_multiprocessor.reset()
        if launch:
            for warp in self.streaming_multiprocessor.warps:
                warp.pc = address
                warp.active_mask = warp.live_mask = (1 << warp.num_threads) - 1

    def configure_warps(self, config: object) -> None:
        """Valida todo el lanzamiento antes de reiniciar/aplicar estado; no toca memoria."""
        config = config_fields(config, {'warp_size', 'warps'}, 'raíz')
        size = config_warp_size(config)
        sm = self.streaming_multiprocessor
        if size != sm.warp_size:
            raise ValueError("config: warp_size no coincide con el sistema")
        entries = config.get('warps')
        if not isinstance(entries, list):
            raise TypeError("config: warps debe ser una lista")
        states = {}
        for index, entry in enumerate(entries):
            label = f'warps[{index}]'
            entry = config_fields(entry, {'id', 'enabled', 'pc', 'active_mask', 'workgroup_id'}, label)
            warp_id = config_integer(entry.get('id'), f'{label}.id')
            if not 0 <= warp_id < sm.num_warps:
                raise ValueError(f"config: {label}.id fuera de rango (0..{sm.num_warps - 1})")
            if warp_id in states:
                raise ValueError(f"config: id de warp duplicado: {warp_id}")
            enabled = entry.get('enabled', True)
            if type(enabled) is not bool:
                raise ValueError(f"config: {label}.enabled debe ser booleano")
            pc = config_integer(entry.get('pc', 0), f'{label}.pc')
            if pc < 0 or pc > MASK32 or pc & 3 or pc + 4 > len(self.memory):
                raise ValueError(f"config: {label}.pc no alineado o fuera de memoria")
            mask = config_integer(entry.get('active_mask', (1 << size) - 1),
                                  f'{label}.active_mask')
            if mask < 0 or mask >= (1 << size) or (enabled and mask == 0):
                raise ValueError(f"config: {label}.active_mask fuera de rango o vacío en warp habilitado")
            group = config_integer(entry.get('workgroup_id', 0), f'{label}.workgroup_id')
            if group < 0:
                raise ValueError("config: workgroup_id debe ser no negativo")
            states[warp_id] = (pc, mask if enabled else 0, group)
        self.fault = None
        sm.reset()
        for warp_id, (pc, mask, group) in states.items():
            sm.warps[warp_id].pc = pc
            sm.warps[warp_id].active_mask = sm.warps[warp_id].live_mask = mask
            sm.warps[warp_id].workgroup_id = group

    def step(self) -> bool:
        """Emite como máximo una instrucción de un warp (round-robin)."""
        return self.streaming_multiprocessor.step()

    def run(self, max_instructions: int = 100_000_000) -> None:
        """Límite absoluto de instrucciones de warp completadas desde la carga."""
        if max_instructions < 0:
            raise ValueError("el límite de instrucciones no puede ser negativo")
        while not self.halted:
            if self.instructions_executed >= max_instructions:
                raise InstructionLimitExceeded(
                    f"límite de {max_instructions} instrucciones de warp alcanzado"
                )
            self.step()

    def stop_with_error(self, fault: Fault) -> None:
        if self.fault is None:
            self.fault = fault

    def dump_memory(self, address: int, size: int, filename: Path) -> None:
        if address < 0 or size < 0 or address + size > len(self.memory):
            raise ValueError("volcado fuera de memoria")
        filename.write_bytes(self.memory[address:address + size])


class StreamingMultiprocessor:
    """Planificador determinista: una instrucción de warp por paso."""

    def __init__(self, memory: bytearray, system: System,
                 num_warps: int = 8, warp_size: int = 8):
        self.system = system
        self.memory = memory
        self.num_warps = num_warps
        self.warp_size = warp_size
        self.warps = [Warp(memory, self, i, warp_size) for i in range(num_warps)]
        self.next_warp = 0

    def reset(self) -> None:
        self.next_warp = 0
        for warp in self.warps:
            warp.reset()

    def step(self) -> bool:
        if self.system.halted:
            return False
        for offset in range(self.num_warps):
            index = (self.next_warp + offset) % self.num_warps
            warp = self.warps[index]
            if not warp.halted and warp.state == 'READY':
                completed = self._step_warp(warp)
                self.next_warp = (index + 1) % self.num_warps
                return completed
        return False

    def release_barriers(self) -> None:
        for group in {w.workgroup_id for w in self.warps}:
            participants = [w for w in self.warps if w.workgroup_id == group and not w.halted]
            if participants and all(w.state == 'WAIT_BAR' for w in participants):
                for w in participants:
                    w.state = 'READY'
                    w.pc = u32(w.pc + 4)
                    w.barrier_generation += 1
                    w.reconverge()

    def _step_warp(self, warp: Warp) -> bool:
        trace = self.system.trace
        if trace is None:
            return warp.step()
        pc, mask = warp.pc, warp.active_mask
        word = None
        if 0 <= pc and not pc & 3 and pc + 4 <= len(self.memory):
            word = struct.unpack_from('<I', self.memory, pc)[0]
        before = {}
        if trace.detail and trace.recording:
            before = {lane.core_id: lane.regs.copy() for lane in warp.processors
                      if mask & (1 << lane.core_id)}
        try:
            completed = warp.step()
        except SimulationError as exc:
            trace(TraceEvent(warp.warp_id, pc, mask, warp.live_mask, word, warp.pc, f'SIMULADOR: {exc}'))
            raise
        details = []
        fault = self.system.fault
        if fault:
            outcome = f'ERROR 0x{fault.code:02X} hilo={fault.core_id}'
            if fault.address is not None:
                outcome += f' direccion=0x{fault.address:08X}'
            outcome += ' (sin commit)'
        else:
            outcome = 'FINISHED' if warp.halted else warp.state
            for lane_id, regs in before.items():
                after = warp.processors[lane_id].regs
                for number, (old, new) in enumerate(zip(regs, after)):
                    if old != new:
                        details.append(f'T{lane_id} R{number}: 0x{old:08X} -> 0x{new:08X}')
                if word is not None and word >> 26 in (0x15, 0x16):
                    op, rd, ra = word >> 26, (word >> 21) & 31, (word >> 16) & 31
                    address = u32(regs[ra] + sign_extend(word & 0xFFFF, 16))
                    value = after[rd] if op == 0x15 else regs[rd]
                    details.append(f'T{lane_id} {"READ" if op == 0x15 else "WRITE"} '
                                   f'[0x{address:08X}] = 0x{value:08X}')
        trace(TraceEvent(warp.warp_id, pc, mask, warp.live_mask, word, warp.pc, outcome, tuple(details)))
        return completed


class Warp:
    """PC compartido; valida todos los hilos antes de confirmar resultados."""

    def __init__(self, memory: bytearray, sm: StreamingMultiprocessor,
                 warp_id: int, num_threads: int = 8):
        self.memory = memory
        self.sm = sm
        self.warp_id = warp_id
        self.num_threads = num_threads
        self.processors = [CPU(memory, self, i) for i in range(num_threads)]
        self.reset()

    @property
    def halted(self) -> bool:
        return self.live_mask == 0

    def reset(self) -> None:
        self.pc = 0
        self.active_mask = 0
        self.live_mask = 0
        self.state = 'READY'
        self.workgroup_id = 0
        self.barrier_generation = 0
        self.barrier_key = None
        self.region_stack: list[SimtRegion] = []
        self.path_stack: list[SimtPath] = []
        self.instructions_executed = 0
        for processor in self.processors:
            processor.reset()

    def reconverge(self) -> None:
        if not self.live_mask:
            self.region_stack.clear()
            self.path_stack.clear()
            self.active_mask = 0
            self.state = 'FINISHED'
            return
        while self.region_stack:
            region = self.region_stack[-1]
            if self.active_mask and self.pc != region.join_pc:
                return
            assert len(self.path_stack) >= region.path_base
            if len(self.path_stack) > region.path_base:
                path = self.path_stack.pop()
                self.pc = path.pending_pc
                self.active_mask = path.pending_mask & self.live_mask
            else:
                self.region_stack.pop()
                self.pc = region.join_pc
                self.active_mask = region.entry_mask & self.live_mask
        assert not self.path_stack
        if not self.active_mask:
            self.sm.system.stop_with_error(Fault(ERROR_SIMT, self.pc, self.warp_id, None))

    def step(self) -> bool:
        if self.sm.system.halted or self.halted or self.state == 'WAIT_BAR':
            return False
        core_id = None
        try:
            instr = read_u32(self.memory, self.pc)
            opcode = instr >> 26
            if not valid_encoding(instr, opcode):
                raise ExecutionFault(ERROR_INVALID_ENCODING)
            if opcode not in {
                0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x09, 0x0A, 0x0C, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15,
                0x16, 0x17, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x2F,
                0x30, 0x31, 0x32, 0x33, 0x3E, 0x3F,
            }:
                raise ExecutionFault(ERROR_INVALID_OPCODE)
            if opcode == 0x3E:
                raise ExecutionFault(ERROR_EXPLICIT_TRAP)
            if opcode == 0x31:  # Reaffirm the innermost region or open a new one.
                target = u32(self.pc + 4 + sign_extend(instr & 0x3FFFFFF, 26) * 4)
                check_address(self.memory, target)
                if self.region_stack and self.region_stack[-1].ssy_pc == self.pc:
                    if self.region_stack[-1].join_pc != target:
                        raise ExecutionFault(ERROR_SIMT)
                else:
                    if len(self.region_stack) >= self.sm.system.simt_region_depth:
                        raise ExecutionFault(ERROR_SIMT)
                    self.region_stack.append(SimtRegion(
                        self.pc, target, self.active_mask, len(self.path_stack)))
                self.pc = u32(self.pc + 4)
                self.instructions_executed += 1
                self.reconverge()
                return True
            if opcode == 0x32:
                if self.active_mask != self.live_mask:
                    raise ExecutionFault(ERROR_BARRIER)
                key = (self.pc, self.barrier_generation)
                if any(w.workgroup_id == self.workgroup_id and w.state == 'WAIT_BAR'
                       and w.barrier_key != key for w in self.sm.warps):
                    raise ExecutionFault(ERROR_BARRIER)
                self.state = 'WAIT_BAR'
                self.barrier_key = key
                self.instructions_executed += 1
                self.sm.release_barriers()
                self.reconverge()
                return True
            results = []
            for processor in self.processors:
                if self.active_mask & (1 << processor.core_id):
                    core_id = processor.core_id
                    results.append((processor, processor.evaluate(instr, self.pc)))
        except ExecutionFault as exc:
            self.sm.system.stop_with_error(
                Fault(exc.code, self.pc, self.warp_id, core_id, exc.address)
            )
            return False

        next_pcs = {result.next_pc for _, result in results}
        if len(next_pcs) != 1:
            if not self.region_stack:
                self.sm.system.stop_with_error(Fault(ERROR_SIMT, self.pc, self.warp_id, None))
                return False
            region = self.region_stack[-1]
            fallthrough = u32(self.pc + 4)
            target = next(pc for pc in next_pcs if pc != fallthrough)
            taken = sum(1 << lane.core_id for lane, result in results
                        if result.next_pc != fallthrough)
            if target == region.join_pc:
                self.active_mask &= ~taken
                next_pcs = {fallthrough}
            elif fallthrough == region.join_pc:
                self.active_mask = taken
                next_pcs = {target}
            else:
                if len(self.path_stack) >= self.sm.system.simt_path_depth:
                    self.sm.system.stop_with_error(Fault(ERROR_SIMT, self.pc, self.warp_id, None))
                    return False
                self.path_stack.append(SimtPath(target, taken))
                self.active_mask &= ~taken
                next_pcs = {fallthrough}
        for processor, result in results:
            processor.regs[:] = result.regs
            if result.store is not None:
                address, value = result.store
                struct.pack_into("<I", self.memory, address, value)
            if result.halted:
                self.active_mask &= ~(1 << processor.core_id)
                self.live_mask &= ~(1 << processor.core_id)
        self.pc = next_pcs.pop()
        self.instructions_executed += 1
        self.reconverge()
        self.sm.release_barriers()
        return True


class CPU:
    """Lane: registros privados; evalúa sin modificar el estado arquitectónico."""

    def __init__(self, memory: bytearray, warp: Warp, core_id: int):
        self.memory = memory
        self.warp = warp
        self.core_id = core_id
        self.reset()

    def reset(self) -> None:
        self.regs = [0] * 32

    def evaluate(self, instr: int, pc: int) -> LaneResult:
        regs = self.regs.copy()
        next_pc = u32(pc + 4)
        halted = False
        store = None
        opcode = instr >> 26

        if opcode == 0x00:  # NOP
            pass

        elif opcode == 0x10:  # MOVI
            rd = (instr >> 21) & 0x1F
            imm16 = instr & 0xFFFF
            regs[rd] = u32(sign_extend(imm16, 16))

        elif opcode == 0x17:  # MOVHI
            rd = (instr >> 21) & 0x1F
            imm16 = instr & 0xFFFF
            regs[rd] = u32(imm16 << 16)

        elif opcode == 0x13:  # ORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            regs[rd] = u32(regs[ra] | imm16)

        elif opcode == 0x01:  # ADD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            regs[rd] = u32(regs[ra] + regs[rb])

        elif opcode == 0x11:  # ADDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            regs[rd] = u32(regs[ra] + imm16)

        elif opcode == 0x02:  # SUB
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            regs[rd] = u32(regs[ra] - regs[rb])

        elif opcode == 0x04:  # AND
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            regs[rd] = regs[ra] & regs[rb]

        elif opcode == 0x05:  # OR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            regs[rd] = regs[ra] | regs[rb]

        elif opcode == 0x06:  # XOR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            regs[rd] = regs[ra] ^ regs[rb]

        elif opcode == 0x07:  # SHL
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            # MiniISA usa únicamente los cinco bits bajos de la cantidad.
            regs[rd] = u32(regs[ra] << (regs[rb] & 0x1F))

        elif opcode == 0x08:  # SHR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            regs[rd] = regs[ra] >> (regs[rb] & 0x1F)

        elif opcode == 0x09:  # SAR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            regs[rd] = u32(s32(regs[ra]) >> (regs[rb] & 0x1F))

        elif opcode == 0x0A:  # MUL
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Producto 32 x 32; conservamos los 32 bits bajos.
            regs[rd] = u32(regs[ra] * regs[rb])

        elif opcode == 0x03:  # MULFX signed Q16.16
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Q16.16 x Q16.16 produce Q32.32. El desplazamiento aritmético
            # restaura la escala Q16.16 antes del wrap final a 32 bits.
            product = s32(regs[ra]) * s32(regs[rb])
            regs[rd] = u32(product >> 16)

        elif opcode == 0x0C:  # DIV signed
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            dividend = s32(regs[ra])
            divisor = s32(regs[rb])
            if divisor == 0:
                raise ExecutionFault(ERROR_DIVISION_BY_ZERO)
            regs[rd] = u32(signed_divide(dividend, divisor))

        elif opcode == 0x12:  # ANDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            # Los inmediatos lógicos se extienden con ceros, no con signo.
            imm16 = instr & 0xFFFF
            regs[rd] = regs[ra] & imm16

        elif opcode == 0x14:  # XORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            regs[rd] = regs[ra] ^ imm16

        elif opcode == 0x15:  # LOAD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(regs[ra] + imm16)
            regs[rd] = read_u32(self.memory, address)

        elif opcode == 0x16:  # STORE
            # En STORE, el campo Rd contiene el registro fuente.
            source = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(regs[ra] + imm16)
            check_address(self.memory, address)
            store = (address, u32(regs[source]))

        elif opcode == 0x20:  # BEQ
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] == regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x21:  # BNE
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] != regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x22:  # BLT signed
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if s32(regs[ra]) < s32(regs[rb]):
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x23:  # BGE signed
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if s32(regs[ra]) >= s32(regs[rb]):
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x24:  # BLTU unsigned
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] < regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x25:  # BGEU unsigned
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] >= regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x2F:  # BRA
            # BRA dispone de un offset signed de 26 bits porque no usa
            # registros. El offset también está expresado en instrucciones.
            offset26 = sign_extend(instr & 0x03FFFFFF, 26)
            next_pc = u32(next_pc + (offset26 << 2))

        elif opcode == 0x30:  # GETTID
            rd = (instr >> 21) & 0x1F
            regs[rd] = self.warp.warp_id * self.warp.num_threads + self.core_id

        elif opcode in (0x33, 0x3F):  # HALT
            halted = True

        elif opcode == 0x3E:  # TRAP
            raise ExecutionFault(ERROR_EXPLICIT_TRAP)

        else:
            raise ExecutionFault(ERROR_INVALID_OPCODE)

        return LaneResult(regs, next_pc, halted, store)

def main() -> int:
    parser = argparse.ArgumentParser(description="Simulador funcional de MiniGPU")
    parser.add_argument("program", type=Path)
    parser.add_argument("--max", type=int, default=100_000_000,
                        help="límite total de instrucciones de warp completadas")
    parser.add_argument("--memory-size", type=lambda x: int(x, 0), default=32 * 1024 * 1024)
    parser.add_argument("--num-warps", type=int, default=8)
    parser.add_argument("--warp-size", type=int, default=None)
    parser.add_argument("--simt-region-depth", type=int, default=MAX_SIMT_REGIONS,
                        help="capacidad de la pila de regiones por warp (por defecto: 8)")
    parser.add_argument("--simt-path-depth", type=int, default=MAX_SIMT_PATHS,
                        help="capacidad de la pila de caminos por warp (por defecto: 8)")
    parser.add_argument("--config", type=Path, help="JSON con PC y máscara inicial de cada warp")
    parser.add_argument("--dump", nargs=3, metavar=("ADDRESS", "SIZE", "FILE"))
    parser.add_argument("--trace", action="store_true", help="traza del scheduler por instrucción de warp")
    parser.add_argument("--trace-detail", action="store_true", help="incluye registros y memoria por hilo")
    parser.add_argument("--trace-limit", type=int, help="máximo de pasos mostrados; no limita la ejecución")
    parser.add_argument("--trace-file", type=Path, help="guarda la traza en UTF-8 en vez de stderr")
    args = parser.parse_args()
    try:
        config = None
        if args.config is not None:
            config = json.loads(args.config.read_text(encoding='utf-8-sig'))
            try:
                size = config_warp_size(config)
            except TypeError as exc:
                raise ValueError(str(exc)) from exc
            if args.warp_size is not None and args.warp_size != size:
                raise ValueError("--warp-size no coincide con warp_size de --config")
        else:
            size = args.warp_size if args.warp_size is not None else 8
        system = System(args.memory_size, args.num_warps, size,
                        simt_region_depth=args.simt_region_depth,
                        simt_path_depth=args.simt_path_depth)
        system.load_program(args.program.read_bytes(), launch=args.config is None)
        if args.config is not None:
            try:
                system.configure_warps(config)
            except TypeError as exc:
                raise ValueError(str(exc)) from exc
        tracing = args.trace or args.trace_detail or args.trace_file is not None or args.trace_limit is not None
        if args.trace_limit is not None and args.trace_limit < 0:
            raise ValueError('trace-limit no puede ser negativo')
        if tracing:
            if args.trace_file is not None:
                protected = [args.program, args.config]
                if args.dump:
                    protected.append(Path(args.dump[2]))
                if any(path is not None and path.resolve() == args.trace_file.resolve() for path in protected):
                    raise ValueError('trace-file debe ser distinto del programa, configuración y dump')
            output = args.trace_file.open('w', encoding='utf-8') if args.trace_file else nullcontext(sys.stderr)
            with output as stream:
                system.trace = TextTrace(stream, detail=args.trace_detail, limit=args.trace_limit)
                try:
                    system.run(args.max)
                except SimulationError as exc:
                    system.trace.finish(f'SIMULADOR: {exc}')
                    raise
                else:
                    system.trace.finish(f'{system.fault or "HALT"}; '
                                        f'{system.instructions_executed} instrucciones de warp')
                finally:
                    system.trace = None
        else:
            system.run(args.max)
        if system.fault:
            fault = system.fault
            print(f"ERROR 0x{fault.code:02X} en PC=0x{fault.pc:08X}, "
                  f"warp={fault.warp_id}, hilo={fault.core_id}, "
                  f"dirección={fault.address}; "
                  f"{system.instructions_executed} instrucciones de warp", file=sys.stderr)
        else:
            print(f"HALT tras {system.instructions_executed} instrucciones de warp")
        if args.dump:
            address, size, filename = args.dump
            system.dump_memory(int(address, 0), int(size, 0), Path(filename))
        return 1 if system.error else 0
    except (OSError, ValueError, SimulationError) as exc:
        print(f"Simulador: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
