"""Eventos y presentación de la ejecución funcional; no modela ciclos."""

from dataclasses import dataclass
from typing import TextIO

NAMES = {
    0x00: 'NOP', 0x01: 'ADD', 0x02: 'SUB', 0x03: 'MULFX', 0x04: 'AND',
    0x05: 'OR', 0x06: 'XOR', 0x07: 'SHL', 0x08: 'SHR', 0x09: 'SAR',
    0x0A: 'MUL', 0x0C: 'DIV', 0x10: 'MOVI', 0x11: 'ADDI', 0x12: 'ANDI',
    0x13: 'ORI', 0x14: 'XORI', 0x15: 'LOAD', 0x16: 'STORE', 0x17: 'MOVHI',
    0x20: 'BEQ', 0x21: 'BNE', 0x22: 'BLT', 0x23: 'BGE', 0x24: 'BLTU',
    0x25: 'BGEU', 0x2F: 'BRA', 0x30: 'GETTID', 0x3E: 'TRAP', 0x3F: 'HALT',
}


def instruction_text(word: int | None) -> str:
    if word is None:
        return '<FETCH>'
    op, rd, ra, rb = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
    name = NAMES.get(op)
    if name is None:
        return f'.word 0x{word:08X}'
    if op in (0, 0x3E, 0x3F):
        return name
    if op == 0x30:
        return f'{name} R{rd}'
    if op == 0x2F:
        offset = word & 0x3FFFFFF
        if offset & 0x2000000:
            offset -= 1 << 26
        return f'{name} {offset:+d}'
    if op < 0x10:
        return f'{name} R{rd}, R{ra}, R{rb}'
    immediate = word & 0xFFFF
    if op in (0x10, 0x11, 0x15, 0x16, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25):
        immediate = immediate - 65536 if immediate & 0x8000 else immediate
    if op in (0x10, 0x17):
        return f'{name} R{rd}, {immediate}'
    return f'{name} R{rd}, R{ra}, {immediate}'


@dataclass(frozen=True)
class TraceEvent:
    warp_id: int
    pc: int
    mask: int
    instruction: int | None
    next_pc: int
    outcome: str
    details: tuple[str, ...] = ()


class TextTrace:
    def __init__(self, stream: TextIO, *, detail: bool = False, limit: int | None = None):
        if limit is not None and limit < 0:
            raise ValueError('trace-limit no puede ser negativo')
        self.stream = stream
        self.detail = detail
        self.limit = limit
        self.steps = 0
        print('PASO    WARP PC          MASK INSTRUCCION                  RESULTADO', file=stream)

    @property
    def recording(self) -> bool:
        return self.limit is None or self.steps < self.limit

    def __call__(self, event: TraceEvent) -> None:
        self.steps += 1
        if self.limit is not None and self.steps > self.limit:
            if self.steps == self.limit + 1:
                print(f'... traza limitada a {self.limit} pasos; la ejecucion continua', file=self.stream)
            return
        print(f'{self.steps:06d}  W{event.warp_id:<3} 0x{event.pc:08X}  {event.mask:02X}   '
              f'{instruction_text(event.instruction):<28} '
              f'-> 0x{event.next_pc:08X} {event.outcome}', file=self.stream)
        if self.detail:
            for line in event.details:
                print(f'        {line}', file=self.stream)
        self.stream.flush()

    def finish(self, message: str) -> None:
        print(f'FIN: {message}', file=self.stream, flush=True)
