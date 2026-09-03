import struct
import unittest

from minicpu_sim import CPU


def encode_r(opcode: int, rd: int, ra: int, rb: int) -> int:
    return (opcode << 26) | (rd << 21) | (ra << 16) | (rb << 11)


def encode_i(opcode: int, rd: int, ra: int, immediate: int) -> int:
    return (opcode << 26) | (rd << 21) | (ra << 16) | (immediate & 0xFFFF)


class MiniCpuNewInstructionsTest(unittest.TestCase):
    def execute(
        self,
        instruction: int,
        registers: dict[int, int] | None = None,
    ) -> CPU:
        cpu = CPU(memory_size=64)
        struct.pack_into("<I", cpu.memory, 0, instruction)

        if registers:
            for register, value in registers.items():
                cpu.regs[register] = value

        cpu.step()
        return cpu

    def test_nop_only_advances_pc(self) -> None:
        cpu = self.execute(0x00000000, {1: 0x12345678})
        self.assertEqual(cpu.pc, 4)
        self.assertEqual(cpu.regs[1], 0x12345678)
        self.assertEqual(cpu.instructions_executed, 1)

    def test_register_logic(self) -> None:
        values = {1: 0xF0F00F0F, 2: 0x0FF033CC}
        cases = (
            (0x04, 0x00F0030C),
            (0x05, 0xFFF03FCF),
            (0x06, 0xFF003CC3),
        )

        for opcode, expected in cases:
            with self.subTest(opcode=opcode):
                cpu = self.execute(encode_r(opcode, 3, 1, 2), values)
                self.assertEqual(cpu.regs[3], expected)

    def test_shifts_use_only_five_low_bits(self) -> None:
        registers = {1: 0x80000001, 2: 33}
        cases = (
            (0x07, 0x00000002),
            (0x08, 0x40000000),
            (0x09, 0xC0000000),
        )

        for opcode, expected in cases:
            with self.subTest(opcode=opcode):
                cpu = self.execute(encode_r(opcode, 3, 1, 2), registers)
                self.assertEqual(cpu.regs[3], expected)

    def test_immediate_logic_is_zero_extended(self) -> None:
        and_cpu = self.execute(
            encode_i(0x12, 2, 1, 0x8001),
            {1: 0xFFFF7FFF},
        )
        xor_cpu = self.execute(
            encode_i(0x14, 2, 1, 0xFFFF),
            {1: 0xFFFF0000},
        )
        self.assertEqual(and_cpu.regs[2], 0x00000001)
        self.assertEqual(xor_cpu.regs[2], 0xFFFFFFFF)

    def test_gettid_returns_zero_on_minicpu(self) -> None:
        instruction = encode_i(0x30, 7, 0, 0)
        cpu = self.execute(instruction, {7: 0xFFFFFFFF})
        self.assertEqual(cpu.regs[7], 0)


if __name__ == "__main__":
    unittest.main()
