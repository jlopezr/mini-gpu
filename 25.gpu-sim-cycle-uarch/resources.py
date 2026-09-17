"""Timing parameters and immutable resource records for the proposed machine."""
from dataclasses import dataclass, field
from collections import Counter


@dataclass(frozen=True)
class Config:
    mul_cycles: int = 4
    div_cycles: int = 32
    shift_per_bit: int = 1
    memory_cycles: int = 17
    lsu_slots: int = 8
    imem_lines: int = 16
    imem_miss_cycles: int = 17

    def __post_init__(self):
        for name in ('mul_cycles', 'div_cycles', 'memory_cycles', 'lsu_slots', 'imem_miss_cycles'):
            value = getattr(self, name)
            if type(value) is not int or value < 1: raise ValueError(f'{name} must be a positive integer')
        for name in ('shift_per_bit', 'imem_lines'):
            value = getattr(self, name)
            if type(value) is not int or value < 0: raise ValueError(f'{name} must be a nonnegative integer')
        if self.imem_lines and self.imem_lines & (self.imem_lines - 1):
            raise ValueError('imem_lines must be zero (ideal fetch) or a power of two')


@dataclass(frozen=True)
class Packet:
    serial: int
    warp: int
    pc: int
    mask: int
    word: int | None = None
    decoded: object = None
    operands: tuple = ()
    results: tuple = ()
    fault: object = None
    remaining: int = 0
    latency: int = 1
    fetch_started: bool = False
    response_ready: bool = False


def execution_cycles(d, operands, cfg):
    if d.op in (3, 0xa, 0xb): return cfg.mul_cycles
    if d.op in (0xc, 0xd, 0xe, 0xf): return cfg.div_cycles
    if d.op in (7, 8, 9):
        amount = max((d.rb if d.word & 0x400 else regs[d.rb] & 31
                      for _, regs in operands), default=0)
        return max(1, amount * cfg.shift_per_bit)
    return 1


def transaction_count(results):
    """16-byte coalescing; duplicate/overlapping stores need separate rounds."""
    rounds = {}
    for _, result in results:
        address, size, value, _ = result.access
        line, bits = address // 16, ((1 << size) - 1) << (address % 16)
        if value is None:
            rounds.setdefault(line, [0])
        else:
            slots = rounds.setdefault(line, [])
            for index, occupied in enumerate(slots):
                if not occupied & bits:
                    slots[index] |= bits
                    break
            else:
                slots.append(bits)
    return sum(map(len, rounds.values()))


@dataclass
class Counters:
    cycles: int = 0
    issued: int = 0
    retired: int = 0
    cancelled: int = 0
    lane_ops: int = 0
    stall_x: int = 0
    stall_no_warp: int = 0
    stall_lsu_full: int = 0
    stall_fetch: int = 0
    stall_writeback: int = 0
    writeback_collisions: int = 0
    response_arrival_collisions: int = 0
    simultaneous_completions: int = 0
    wait_mem_cycles: int = 0
    lsu_busy: int = 0
    lsu_occupancy: int = 0
    lsu_transactions: int = 0
    imem_hits: int = 0
    imem_misses: int = 0
    reconvergence: int = 0
    barrier_releases: int = 0
    occupancy: Counter = field(default_factory=Counter)
    instructions: Counter = field(default_factory=Counter)
    multicycle: Counter = field(default_factory=Counter)
    x_cycles_by_opcode: Counter = field(default_factory=Counter)

    def report(self):
        from dataclasses import asdict
        result = asdict(self)
        # dataclasses reconstructs Counter from pairs; explicitly serialize mappings.
        for name in ('occupancy', 'instructions', 'multicycle', 'x_cycles_by_opcode'):
            result[name] = dict(getattr(self, name))
        groups = dict.fromkeys(('ALU', 'MUL', 'SHIFT', 'DIV', 'CONTROL', 'FAULT'), 0)
        for opcode, cycles in self.x_cycles_by_opcode.items():
            group = ('MUL' if opcode in ('MULFX', 'MUL', 'MULHI') else
                     'SHIFT' if opcode in ('SHL', 'SHR', 'SAR') else
                     'DIV' if opcode in ('DIV', 'DIVU', 'REM', 'REMU') else
                     'CONTROL' if opcode in ('BEQ', 'BNE', 'BLT', 'BGE', 'BLTU', 'BGEU', 'BRA') else
                     'FAULT' if opcode == 'FAULT' else 'ALU')
            groups[group] += cycles
        result['x_cycles_by_unit'] = groups
        result['cpi'] = self.cycles / self.retired if self.retired else None
        result['x_utilization'] = self.occupancy['X'] / self.cycles if self.cycles else 0
        result['stage_utilization'] = {s: self.occupancy[s] / self.cycles if self.cycles else 0 for s in 'SFIDXW'}
        return result
