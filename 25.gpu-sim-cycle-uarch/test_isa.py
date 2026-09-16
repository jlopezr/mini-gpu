"""Hito 1: independent architectural oracle and boundary encodings."""
import random
import sys
import unittest
from pathlib import Path

from isa import decode, execute, ISAError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '2.cpu-sim-func'))
from minicpu_sim import CPU


class DatapathTests(unittest.TestCase):
    def test_differential_scalar_alu(self):
        rng = random.Random(2501)
        cpu = CPU(memory_size=256)
        for op in (*range(16), *range(0x10, 0x15), 0x17, *range(0x20, 0x28), 0x2f, 0x30):
            for trial in range(40):
                regs = [0] + [rng.getrandbits(32) for _ in range(31)]
                word = op << 26
                if op not in (0, 0x2f):
                    word |= (trial % 32) << 21
                    if op not in (0x10, 0x17, 0x30): word |= 2 << 16
                    if op < 16 or op in (0x26, 0x27): word |= 3 << 11
                    elif op != 0x30: word |= rng.getrandbits(16)
                    if op in (7, 8, 9) and trial % 2: word |= 0x400
                cpu.reset()
                cpu.memory[:4] = word.to_bytes(4, 'little')
                cpu.regs[:] = regs
                result = execute(decode(word, 0), regs)
                cpu.step()
                expected = regs.copy()
                if result.write: expected[result.write[0]] = result.write[1]
                self.assertFalse(cpu.error, hex(word))
                self.assertEqual(expected, cpu.regs, hex(word))
                self.assertEqual(result.next_pc, cpu.pc)

    def test_signed_corner_cases(self):
        for a, b in ((0x80000000, 0xffffffff), (0xfffffff9, 2), (7, 0xfffffffe)):
            regs = [0, a, b] + [0] * 29
            for op in (3, 0xb, 0xc, 0xd, 0xe, 0xf):
                word = op << 26 | 3 << 21 | 1 << 16 | 2 << 11
                cpu = CPU(256)
                cpu.memory[:4] = word.to_bytes(4, 'little')
                cpu.regs[:] = regs
                cpu.step()
                self.assertEqual(execute(decode(word, 0), regs).write[1], cpu.regs[3])

    def test_errors_and_reserved_bits(self):
        for op in (0xc, 0xd, 0xe, 0xf):
            with self.assertRaises(ISAError) as caught:
                execute(decode(op << 26, 0), [0] * 32)
            self.assertEqual(caught.exception.code, 4)
        for op in (0, 1, 7, 0xb, 0x26, 0x30, 0x32, 0x33, 0x3f):
            with self.assertRaises(ISAError) as caught: decode(op << 26 | 1, 0)
            self.assertEqual(caught.exception.code, 5)
        for op in (0x1e, 0x28, 0x2c, 0x2d, 0x2e, 0x34):
            with self.assertRaises(ISAError) as caught: decode(op << 26, 0)
            self.assertEqual(caught.exception.code, 1)


if __name__ == '__main__': unittest.main()
