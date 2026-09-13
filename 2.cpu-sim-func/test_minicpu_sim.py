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


class ShiftImmediateTest(unittest.TestCase):
    """Opcion B de propuesta-v0.2.md §4.2: el bit 10 y la cantidad en `Rb`."""

    IMMEDIATE = 1 << 10

    def execute(self, instruction: int, registers=None) -> CPU:
        cpu = CPU(memory_size=64)
        struct.pack_into("<I", cpu.memory, 0, instruction)
        for register, value in (registers or {}).items():
            cpu.regs[register] = value
        cpu.step()
        return cpu

    def test_la_cantidad_sale_del_campo_y_no_del_registro(self) -> None:
        """El caso que un test descuidado no ve.

        Con `R4 = 4` un multiplexor al reves daria el mismo resultado. Aqui R4
        vale 17, asi que leer el registro en lugar del campo se nota.
        """
        cpu = self.execute(
            encode_r(0x07, 1, 2, 4) | self.IMMEDIATE, {2: 1, 4: 17})
        self.assertEqual(cpu.regs[1], 1 << 4)

    def test_bordes_cero_y_treinta_y_uno(self) -> None:
        casos = (
            (0x07, 0, 0x89ABCDEF), (0x07, 31, 0x80000000),
            (0x08, 0, 0x89ABCDEF), (0x08, 31, 0x00000001),
            (0x09, 0, 0x89ABCDEF), (0x09, 31, 0xFFFFFFFF),
        )
        for opcode, cantidad, esperado in casos:
            with self.subTest(opcode=opcode, cantidad=cantidad):
                cpu = self.execute(
                    encode_r(opcode, 1, 2, cantidad) | self.IMMEDIATE,
                    {2: 0x89ABCDEF})
                self.assertEqual(cpu.regs[1], esperado)

    def test_coincide_con_la_forma_con_registro(self) -> None:
        for opcode in (0x07, 0x08, 0x09):
            for cantidad in range(32):
                inmediata = self.execute(
                    encode_r(opcode, 1, 2, cantidad) | self.IMMEDIATE,
                    {2: 0x89ABCDEF})
                registro = self.execute(
                    encode_r(opcode, 1, 2, 3), {2: 0x89ABCDEF, 3: cantidad})
                self.assertEqual(inmediata.regs[1], registro.regs[1],
                                 (opcode, cantidad))

    def test_el_campo_reservado_pasa_a_ser_extra_9_0(self) -> None:
        # `extra[10]` solo es valido: es el modo inmediato.
        cpu = self.execute(encode_r(0x07, 1, 2, 3) | self.IMMEDIATE, {2: 1})
        self.assertFalse(cpu.error)
        # Cualquier bit de `extra[9:0]` sigue siendo reservado.
        for extra in (1, 1 << 9, self.IMMEDIATE | 8):
            with self.subTest(extra=extra):
                cpu = self.execute(encode_r(0x07, 1, 2, 3) | extra, {2: 1})
                self.assertTrue(cpu.error)
                self.assertEqual(cpu.error_code, 0x05)


class ExtendedAluTest(unittest.TestCase):
    """MULHI, DIVU, REM y REMU. MULHI es SIGNED; ver 1.isa/isa.md §3."""

    def execute(self, opcode: int, a: int, b: int) -> CPU:
        cpu = CPU(memory_size=64)
        struct.pack_into("<I", cpu.memory, 0, encode_r(opcode, 3, 1, 2))
        cpu.regs[1] = a
        cpu.regs[2] = b
        cpu.step()
        return cpu

    def test_mulhi_es_con_signo(self) -> None:
        """-1 x -1 = 1, o sea parte alta 0. Unsigned daria 0xFFFFFFFE."""
        cpu = self.execute(0x0B, 0xFFFFFFFF, 0xFFFFFFFF)
        self.assertEqual(cpu.regs[3], 0x00000000)

    def test_mulhi_y_mul_son_las_dos_mitades_del_mismo_producto(self) -> None:
        casos = (
            (0x00010000, 0x00010000, 0x00000001, 0x00000000),
            (0xFFFFFFFF, 0x00000001, 0xFFFFFFFF, 0xFFFFFFFF),
            (0x7FFFFFFF, 0x7FFFFFFF, 0x3FFFFFFF, 0x00000001),
            (0x80000000, 0x80000000, 0x40000000, 0x00000000),
            (0x80000000, 0x00000002, 0xFFFFFFFF, 0x00000000),
            (0x12345678, 0x9ABCDEF0, 0xF8CC93D6, 0x242D2080),
        )
        for a, b, alto, bajo in casos:
            with self.subTest(a=a, b=b):
                self.assertEqual(self.execute(0x0B, a, b).regs[3], alto)
                self.assertEqual(self.execute(0x0A, a, b).regs[3], bajo)

    def test_el_resto_lleva_el_signo_del_dividendo(self) -> None:
        """Los dos casos que separan esta regla del modulo matematico."""
        casos = (
            (7, 2, 3, 1),
            (0xFFFFFFF9, 2, 0xFFFFFFFD, 0xFFFFFFFF),        # -7 / 2
            (7, 0xFFFFFFFE, 0xFFFFFFFD, 1),                 #  7 / -2
            (0xFFFFFFF9, 0xFFFFFFFE, 3, 0xFFFFFFFF),        # -7 / -2
        )
        for a, b, cociente, resto in casos:
            with self.subTest(a=a, b=b):
                self.assertEqual(self.execute(0x0C, a, b).regs[3], cociente)
                self.assertEqual(self.execute(0x0E, a, b).regs[3], resto)

    def test_unsigned_sobre_los_mismos_bits(self) -> None:
        self.assertEqual(self.execute(0x0D, 0xFFFFFFF9, 2).regs[3], 0x7FFFFFFC)
        self.assertEqual(self.execute(0x0F, 0xFFFFFFF9, 2).regs[3], 1)
        # 4294967289 / 4294967294 = 0; signed, -7 / -2 seria 3.
        self.assertEqual(self.execute(0x0D, 0xFFFFFFF9, 0xFFFFFFFE).regs[3], 0)
        self.assertEqual(self.execute(0x0F, 0xFFFFFFF9, 0xFFFFFFFE).regs[3],
                         0xFFFFFFF9)

    def test_el_desbordamiento_de_menos_dos_a_la_31_entre_menos_uno(self) -> None:
        self.assertEqual(self.execute(0x0C, 0x80000000, 0xFFFFFFFF).regs[3],
                         0x80000000)
        self.assertEqual(self.execute(0x0E, 0x80000000, 0xFFFFFFFF).regs[3], 0)

    def test_las_cuatro_paran_con_divisor_cero(self) -> None:
        for opcode in (0x0C, 0x0D, 0x0E, 0x0F):
            with self.subTest(opcode=opcode):
                cpu = self.execute(opcode, 7, 0)
                self.assertTrue(cpu.error)
                self.assertEqual(cpu.error_code, 0x04)
                self.assertEqual(cpu.error_pc, 0)

    def test_exigen_extra_a_cero(self) -> None:
        for opcode in (0x0B, 0x0D, 0x0E, 0x0F):
            with self.subTest(opcode=opcode):
                cpu = CPU(memory_size=64)
                struct.pack_into("<I", cpu.memory, 0,
                                 encode_r(opcode, 3, 1, 2) | 1)
                cpu.step()
                self.assertTrue(cpu.error)
                self.assertEqual(cpu.error_code, 0x05)


class ZeroRegisterTest(unittest.TestCase):
    """R0 cableado a cero: escrituras descartadas, lecturas siempre cero."""

    def run_words(self, words: list[int], registers=None) -> CPU:
        cpu = CPU(memory_size=256)
        data = b"".join(w.to_bytes(4, "little") for w in words)
        cpu.load_program(data)
        for register, value in (registers or {}).items():
            cpu.regs[register] = value
        cpu.run(max_instructions=100)
        return cpu

    def test_todos_los_caminos_de_escritura_descartan_r0(self) -> None:
        """Un solo test por camino no sirve: el simulador escribe R0 desde
        veintidos sitios distintos de `step`, y cada opcode usa el suyo."""
        escrituras = (
            encode_i(0x10, 0, 0, 0xFFFF),       # MOVI R0, -1
            encode_i(0x17, 0, 0, 0xDEAD),       # MOVHI R0, 0xDEAD
            encode_r(0x01, 0, 1, 1),            # ADD R0, R1, R1
            encode_i(0x11, 0, 1, 100),          # ADDI R0, R1, 100
            encode_r(0x07, 0, 1, 2),            # SHL R0, R1, R2
            encode_r(0x0A, 0, 1, 1),            # MUL R0, R1, R1
            encode_r(0x0C, 0, 1, 2),            # DIV R0, R1, R2
            encode_r(0x0B, 0, 1, 1),            # MULHI R0, R1, R1
            encode_i(0x30, 0, 0, 0),            # GETTID R0
            encode_i(0x2C, 0, 0, 0),            # JAL R0, siguiente
        )
        for instruccion in escrituras:
            with self.subTest(opcode=instruccion >> 26):
                cpu = self.run_words([instruccion, 0xFC000000], {1: 7, 2: 4})
                self.assertEqual(cpu.regs[0], 0)

    def test_r0_leido_vale_cero_en_los_dos_operandos(self) -> None:
        cpu = self.run_words([
            encode_r(0x02, 3, 1, 0),            # SUB R3, R1, R0
            encode_r(0x02, 4, 0, 1),            # SUB R4, R0, R1
            0xFC000000,
        ], {1: 7})
        self.assertEqual(cpu.regs[3], 7)
        self.assertEqual(cpu.regs[4], 0xFFFFFFF9)

    def test_una_escritura_descartada_no_deja_rastro(self) -> None:
        cpu = self.run_words([
            encode_i(0x10, 0, 0, 99),           # MOVI R0, 99
            encode_r(0x01, 2, 0, 1),            # ADD R2, R0, R1
            0xFC000000,
        ], {1: 7})
        self.assertEqual(cpu.regs[2], 7)

    def test_jalr_r0_es_un_jr_completo(self) -> None:
        """La razon del cambio: con esto, 0x2E queda reclamable."""
        cpu = self.run_words([
            encode_i(0x10, 1, 0, 0x0C),         # MOVI R1, 0x0C
            encode_i(0x2D, 0, 1, 0),            # JALR R0, R1, 0
            encode_i(0x10, 2, 0, 99),           # saltada
            encode_i(0x10, 2, 0, 42),           # 0x0C
            0xFC000000,
        ])
        self.assertEqual(cpu.regs[2], 42)
        self.assertEqual(cpu.regs[0], 0)


if __name__ == "__main__":
    unittest.main()
