"""Independent exact-rational checks for FP32 and CPU decode/encoding."""
from fractions import Fraction
import random
import unittest

from minicpu_core import CPU, ERROR_INVALID_ENCODING
from tools.fp32 import fp32_binary


def exact_value(bits):
    e = (bits >> 23) & 255
    if e == 0:
        return Fraction(0)
    m = (bits & 0x7fffff) | 0x800000
    return (-1 if bits >> 31 else 1) * Fraction(m) * Fraction(2) ** (e - 150)


def exact_round(value):
    sign = int(value < 0)
    value = abs(value)
    if not value:
        return 0
    n, d = value.numerator, value.denominator
    exponent = n.bit_length() - d.bit_length()
    if value < Fraction(2) ** exponent:
        exponent -= 1
    scaled = value / Fraction(2) ** max(exponent - 23, -149)
    q, r = divmod(scaled.numerator, scaled.denominator)
    if 2 * r > scaled.denominator or (2 * r == scaled.denominator and q & 1):
        q += 1
    if exponent < -126:
        return (sign << 31) | (0x00800000 if q >= 0x800000 else 0)
    if q == 0x1000000:
        q >>= 1
        exponent += 1
    if exponent > 127:
        return (sign << 31) | 0x7f800000
    return (sign << 31) | ((exponent + 127) << 23) | (q & 0x7fffff)


class FP32Test(unittest.TestCase):
    def test_exact_rational_reference(self):
        rng = random.Random(38)
        for op in range(4):
            for _ in range(2000):
                a = rng.getrandbits(32)
                b = rng.getrandbits(32)
                # Finite normal operands; special values checked separately.
                a = (a & 0x807fffff) | (rng.randrange(1, 255) << 23)
                b = (b & 0x807fffff) | (rng.randrange(1, 255) << 23)
                x, y = exact_value(a), exact_value(b)
                if op == 0:
                    result = x + y
                elif op == 1:
                    result = x - y
                elif op == 2:
                    result = x * y
                else:
                    result = x / y
                self.assertEqual(fp32_binary(op, a, b), exact_round(result),
                                 f'op={op} a={a:08x} b={b:08x}')

    def test_special_values_and_rounding(self):
        cases = [
            (0, 0, 0, 0), (0, 0x80000000, 0x80000000, 0x80000000),
            (1, 0x3f800000, 0x3f800000, 0),
            (0, 0x7f800000, 0xff800000, 0x7fc00000),
            (0, 0x7fa12345, 0, 0x7fc00000),
            (0, 0x3f800000, 0x33800000, 0x3f800000),
            (0, 0x3f800001, 0x33800000, 0x3f800002),
            (2, 0x7f800000, 1, 0x7fc00000),
            (2, 0x00800000, 0x3f7fffff, 0x00800000),
            (2, 0x00800000, 0x3f000000, 0),
            (3, 0, 1, 0x7fc00000),
            (3, 0x3f800000, 0x80000001, 0xff800000),
            (3, 0x7f800000, 0x7f800000, 0x7fc00000),
            (3, 0x3f800000, 0xff800000, 0x80000000),
            (3, 0x7f7fffff, 0x00800000, 0x7f800000),
            (3, 0x00800000, 0x7f7fffff, 0),
            (3, 0x3f800000, 0x40400000, 0x3eaaaaab),
        ]
        for op, a, b, expected in cases:
            with self.subTest(op=op, a=hex(a), b=hex(b)):
                self.assertEqual(fp32_binary(op, a, b), expected)

    def test_cpu_decode_and_reserved_bits(self):
        for op in range(4):
            cpu = CPU(1024)
            cpu.regs[1], cpu.regs[2] = 0x3fc00000, 0x40000000
            instruction = ((0x38 + op) << 26) | (3 << 21) | (1 << 16) | (2 << 11)
            cpu.load_program(instruction.to_bytes(4, 'little') + (0xfc000000).to_bytes(4, 'little'))
            cpu.run(10)
            self.assertEqual(cpu.regs[3], fp32_binary(op, cpu.regs[1], cpu.regs[2]))
            for bit in range(11):
                cpu = CPU(1024)
                cpu.load_program((instruction | (1 << bit)).to_bytes(4, 'little'))
                cpu.run(10)
                self.assertEqual(cpu.error_code, ERROR_INVALID_ENCODING)
                self.assertEqual(cpu.pc, 0)
                self.assertEqual(cpu.regs[3], 0)
