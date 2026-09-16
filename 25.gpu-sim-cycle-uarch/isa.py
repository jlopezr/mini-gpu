"""Pure MiniISA datapath. No GPU state, clock, memory mutation or CPU FSM.

The functional simulators remain independent differential oracles.
"""
from dataclasses import dataclass

MASK = 0xffffffff
MEMORY = frozenset((0x15, 0x16, *range(0x18, 0x1e)))
STORES = frozenset((0x16, 0x1a, 0x1d))
SPECIAL = frozenset((0x31, 0x32, 0x33, 0x3f))
SUPPORTED = frozenset((*range(0x1e), *range(0x20, 0x28), 0x2f,
                       0x30, 0x31, 0x32, 0x33, 0x3e, 0x3f))
NAMES = dict(enumerate(('NOP ADD SUB MULFX AND OR XOR SHL SHR SAR MUL MULHI '
                        'DIV DIVU REM REMU MOVI ADDI ANDI ORI XORI LOAD STORE MOVHI '
                        'LOADB LOADUB STOREB LOADH LOADUH STOREH').split()))
NAMES.update(zip(range(0x20, 0x28), 'BEQ BNE BLT BGE BLTU BGEU SLT SLTU'.split()))
NAMES.update({0x2f: 'BRA', 0x30: 'GETTID', 0x31: 'SSY', 0x32: 'BAR',
              0x33: 'EXIT', 0x3e: 'TRAP', 0x3f: 'HALT'})


def signed(x, bits=32):
    x &= (1 << bits) - 1
    return x - (1 << bits) if x & (1 << (bits - 1)) else x


class ISAError(Exception):
    def __init__(self, code, address=None):
        self.code, self.address = code, address
        super().__init__(f'MiniISA error {code}, address={address}')


@dataclass(frozen=True)
class Decoded:
    word: int
    op: int
    rd: int
    ra: int
    rb: int
    imm: int
    seq: int
    target: int


def decode(word, pc):
    op, rd, ra, rb = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31
    if op not in SUPPORTED:
        raise ISAError(1)
    invalid = False
    if op in (0, 0x32, 0x33, 0x3e, 0x3f):
        invalid = bool(word & 0x3ffffff)
    elif op in (7, 8, 9):
        invalid = bool(word & 0x3ff)
    elif op in (*range(1, 16), 0x26, 0x27):
        invalid = bool(word & 0x7ff)
    elif op in (0x10, 0x17):
        invalid = ra != 0
    elif op == 0x30:
        invalid = bool(word & 0x1fffff)
    if invalid:
        raise ISAError(5)
    seq = (pc + 4) & MASK
    offset = signed(word, 26 if op in (0x2f, 0x31) else 16)
    return Decoded(word, op, rd, ra, rb, signed(word, 16), seq, (seq + 4 * offset) & MASK)


@dataclass(frozen=True)
class Result:
    next_pc: int
    write: tuple[int, int] | None = None
    # address, width, store data (None means load), signed load
    access: tuple[int, int, int | None, bool] | None = None


def execute(d, registers, tid=0):
    """Evaluate latched operands; a memory operation returns a request, not data."""
    r = (0, *registers[1:])
    a, b, op = r[d.ra], r[d.rb], d.op
    value = None
    pc = d.seq
    if op == 0x3e:
        raise ISAError(3)
    if op == 1: value = a + b
    elif op == 2: value = a - b
    elif op in (3, 0xa, 0xb):
        value = (signed(a) * signed(b)) >> {3: 16, 0xa: 0, 0xb: 32}[op]
    elif op == 4: value = a & b
    elif op == 5: value = a | b
    elif op == 6: value = a ^ b
    elif op in (7, 8, 9):
        n = d.rb if d.word & 0x400 else b & 31
        value = a << n if op == 7 else a >> n if op == 8 else signed(a) >> n
    elif op in (0xc, 0xd, 0xe, 0xf):
        a, b = (signed(a), signed(b)) if op in (0xc, 0xe) else (a, b)
        if b == 0: raise ISAError(4)
        q = abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)
        value = q if op in (0xc, 0xd) else a - q * b
    elif op == 0x10: value = d.imm
    elif op == 0x11: value = a + d.imm
    elif op == 0x12: value = a & (d.word & 0xffff)
    elif op == 0x13: value = a | (d.word & 0xffff)
    elif op == 0x14: value = a ^ (d.word & 0xffff)
    elif op == 0x17: value = d.word << 16
    elif op in MEMORY:
        size = 4 if op in (0x15, 0x16) else 1 if op in (0x18, 0x19, 0x1a) else 2
        return Result(pc, access=((a + d.imm) & MASK, size,
                      r[d.rd] if op in STORES else None, op in (0x18, 0x1b)))
    elif 0x20 <= op <= 0x25:
        a, b = r[d.rd], r[d.ra]
        take = (a == b, a != b, signed(a) < signed(b), signed(a) >= signed(b), a < b, a >= b)[op - 0x20]
        if take: pc = d.target
    elif op == 0x26: value = int(signed(a) < signed(b))
    elif op == 0x27: value = int(a < b)
    elif op == 0x2f: pc = d.target
    elif op == 0x30: value = tid
    return Result(pc, (d.rd, value & MASK) if value is not None and d.rd else None)


def check_access(memory_size, address, size):
    if address < 0 or address % size or address + size > memory_size:
        raise ISAError(2, address)
