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


class SubwordAccessTest(unittest.TestCase):
    """Accesos de 8 y 16 bits: opcodes 0x18..0x1D."""

    DATA = 32  # Lejos de la instrucción, que vive en la dirección 0.

    def run_one(self, instruction: int, word: int, registers=None) -> CPU:
        cpu = CPU(memory_size=64)
        struct.pack_into("<I", cpu.memory, 0, instruction)
        struct.pack_into("<I", cpu.memory, self.DATA, word)
        for register, value in (registers or {}).items():
            cpu.regs[register] = value
        cpu.regs[1] = self.DATA
        cpu.step()
        return cpu

    def test_loads_extend_according_to_opcode(self) -> None:
        # 0xBEEFAA78: el byte 1 y las dos mitades tienen el bit alto a uno, así
        # que signo y ceros dan resultados distintos en todos los casos.
        cases = (
            (0x19, 1, 0x000000AA),  # LOADUB
            (0x18, 1, 0xFFFFFFAA),  # LOADB
            (0x19, 0, 0x00000078),
            (0x18, 0, 0x00000078),
            (0x1C, 2, 0x0000BEEF),  # LOADUH
            (0x1B, 2, 0xFFFFBEEF),  # LOADH
            (0x1C, 0, 0x0000AA78),
            (0x1B, 0, 0xFFFFAA78),
        )
        for opcode, offset, expected in cases:
            with self.subTest(opcode=opcode, offset=offset):
                cpu = self.run_one(encode_i(opcode, 3, 1, offset), 0xBEEFAA78)
                self.assertEqual(cpu.regs[3], expected)

    def test_stores_touch_only_their_own_bytes(self) -> None:
        cases = (
            (0x1A, 1, 0x000000AA, 0x1234AA78),  # STOREB
            (0x1A, 3, 0x000000AA, 0xAA345678),
            (0x1D, 2, 0xFFFFBEEF, 0xBEEF5678),  # STOREH, solo los 16 bajos
            (0x1D, 0, 0xFFFFBEEF, 0x1234BEEF),
        )
        for opcode, offset, value, expected in cases:
            with self.subTest(opcode=opcode, offset=offset):
                cpu = self.run_one(
                    encode_i(opcode, 2, 1, offset), 0x12345678, {2: value}
                )
                stored = struct.unpack_from("<I", cpu.memory, self.DATA)[0]
                self.assertEqual(stored, expected)

    def test_odd_halfword_address_traps(self) -> None:
        for opcode in (0x1B, 0x1C, 0x1D):
            with self.subTest(opcode=opcode):
                cpu = self.run_one(encode_i(opcode, 2, 1, 1), 0x12345678)
                self.assertTrue(cpu.error)
                self.assertEqual(cpu.error_code, 0x02)
                self.assertEqual(cpu.pc, 0)

    def test_odd_byte_address_is_legal(self) -> None:
        cpu = self.run_one(encode_i(0x19, 3, 1, 3), 0x12345678)
        self.assertFalse(cpu.error)
        self.assertEqual(cpu.regs[3], 0x12)


class CallTest(unittest.TestCase):
    """Llamadas y saltos indirectos: opcodes 0x2C..0x2E."""

    def run_one(self, instruction: int, at: int = 0, registers=None) -> CPU:
        cpu = CPU(memory_size=256)
        struct.pack_into("<I", cpu.memory, at, instruction)
        for register, value in (registers or {}).items():
            cpu.regs[register] = value
        cpu.pc = at
        cpu.step()
        return cpu

    def test_jal_saves_link_and_jumps_in_words(self) -> None:
        # Desde 0x10, offset +4 palabras: destino 0x10+4+16 = 0x24.
        cpu = self.run_one(encode_i(0x2C, 31, 0, 4), at=0x10)
        self.assertEqual(cpu.pc, 0x24)
        self.assertEqual(cpu.regs[31], 0x14)

    def test_jal_offset_is_signed(self) -> None:
        cpu = self.run_one(encode_i(0x2C, 31, 0, -4), at=0x40)
        self.assertEqual(cpu.pc, 0x34)
        self.assertEqual(cpu.regs[31], 0x44)

    def test_jalr_adds_a_word_displacement_to_the_register(self) -> None:
        cpu = self.run_one(encode_i(0x2D, 30, 5, 2), at=0x10, registers={5: 0x40})
        self.assertEqual(cpu.pc, 0x48)
        self.assertEqual(cpu.regs[30], 0x14)

    def test_jalr_can_reuse_the_source_as_link(self) -> None:
        # Rd == Ra: el destino se calcula antes de escribir el enlace.
        cpu = self.run_one(encode_i(0x2D, 5, 5, 0), at=0x10, registers={5: 0x40})
        self.assertEqual(cpu.pc, 0x40)
        self.assertEqual(cpu.regs[5], 0x14)

    def test_jr_does_not_write_any_link(self) -> None:
        cpu = self.run_one(encode_i(0x2E, 0, 7, 0), at=0x10, registers={7: 0x20})
        self.assertEqual(cpu.pc, 0x20)
        self.assertEqual(cpu.regs[0], 0)

    def test_indirect_targets_drop_the_low_two_bits(self) -> None:
        # No es un error: el RTL enmascara en vez de abrir una ruta de trap.
        for opcode, registers in ((0x2E, {7: 0x22}), (0x2D, {7: 0x22})):
            with self.subTest(opcode=opcode):
                cpu = self.run_one(
                    encode_i(opcode, 0 if opcode == 0x2E else 30, 7, 0),
                    at=0x10,
                    registers=registers,
                )
                self.assertFalse(cpu.error)
                self.assertEqual(cpu.pc, 0x20)

    def test_reserved_fields_are_validated(self) -> None:
        # JAL con campo fuente puesto y JR con destino o inmediato puestos.
        for instruction in (
            encode_i(0x2C, 31, 1, 0),
            encode_i(0x2E, 1, 7, 0),
            encode_i(0x2E, 0, 7, 4),
        ):
            with self.subTest(instruction=instruction):
                cpu = self.run_one(instruction, at=0x10, registers={7: 0x20})
                self.assertTrue(cpu.error)
                self.assertEqual(cpu.error_code, 0x05)
                self.assertEqual(cpu.pc, 0x10)

    def test_call_and_return_round_trip(self) -> None:
        cpu = CPU(memory_size=256)
        program = (
            encode_i(0x2C, 31, 0, 3),       # 0x00 JAL R31, 0x10
            encode_i(0x10, 2, 0, 0x1111),   # 0x04 MOVI R2, 0x1111
            encode_i(0x3F, 0, 0, 0),        # 0x08 HALT
            0x00000000,                     # 0x0C NOP
            encode_i(0x10, 3, 0, 0x2222),   # 0x10 MOVI R3, 0x2222
            encode_i(0x2E, 0, 31, 0),       # 0x14 JR R31
        )
        for index, word in enumerate(program):
            struct.pack_into("<I", cpu.memory, 4 * index, word)

        cpu.run(max_instructions=100)
        self.assertTrue(cpu.halted)
        self.assertFalse(cpu.error)
        self.assertEqual(cpu.regs[2], 0x1111)
        self.assertEqual(cpu.regs[3], 0x2222)
        self.assertEqual(cpu.regs[31], 0x04)
        self.assertEqual(cpu.instructions_executed, 5)


if __name__ == "__main__":
    unittest.main()
