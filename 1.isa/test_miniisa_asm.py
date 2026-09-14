"""Pruebas del ensamblador: directivas de datos y etiquetas como inmediato.

El resto del ensamblador se prueba de hecho en cada caso de `x.tests`, que
ensambla programas reales. Lo que se fija aqui es lo que ese camino NO ejercita:
las directivas `.word` y `.string`, y la aritmetica de etiquetas alrededor de
ellas, que es donde un error deja todas las etiquetas posteriores mal sin que
nada se queje.
"""

from __future__ import annotations

import unittest

from miniisa_asm import AsmError, assemble, first_pass, strip_comment


class StripCommentTest(unittest.TestCase):

    def test_comentario_normal(self):
        self.assertEqual(strip_comment("ADD R1, R2, R3  ; suma"), "ADD R1, R2, R3")
        self.assertEqual(strip_comment("NOP # nada"), "NOP")

    def test_dentro_de_comillas_no_es_comentario(self):
        """Desde que existe `.string`, un `;` puede ser parte del mensaje."""
        self.assertEqual(strip_comment('.string "a ; b"'), '.string "a ; b"')
        self.assertEqual(strip_comment('.string "x # y"  ; de verdad'),
                         '.string "x # y"')

    def test_comillas_escapadas(self):
        self.assertEqual(strip_comment('.string "di \\"hola\\"" ; ya'),
                         '.string "di \\"hola\\""')


class WordDirectiveTest(unittest.TestCase):

    def test_valores_sueltos(self):
        self.assertEqual(assemble(".word 1, 2, 0x10"), [1, 2, 16])

    def test_negativos_en_complemento_a_dos(self):
        self.assertEqual(assemble(".word -1"), [0xFFFFFFFF])

    def test_acepta_etiquetas(self):
        """Es lo que permite escribir una tabla de direcciones."""
        fuente = "\n".join([
            "    BRA fin",
            "destino:",
            "    NOP",
            "fin:",
            "    .word destino, 0",
        ])
        palabras = assemble(fuente)
        self.assertEqual(palabras[-2], 4)   # `destino` esta en 0x04
        self.assertEqual(palabras[-1], 0)

    def test_fuera_de_rango(self):
        with self.assertRaises(AsmError):
            assemble(".word 0x1_0000_0000")

    def test_sin_operandos(self):
        with self.assertRaises(AsmError):
            assemble(".word")


class StringDirectiveTest(unittest.TestCase):

    def test_termina_en_nul_y_se_rellena(self):
        # "ok" son dos bytes, mas el NUL son tres, y se rellena hasta cuatro.
        self.assertEqual(assemble('.string "ok"'), [0x00006B6F])

    def test_ocupa_un_numero_entero_de_palabras(self):
        # Cuatro caracteres mas el NUL son cinco: dos palabras.
        self.assertEqual(len(assemble('.string "abcd"')), 2)

    def test_escapes(self):
        self.assertEqual(assemble('.string "\\n"'), [0x0000000A])
        self.assertEqual(assemble('.string "\\\\"'), [0x0000005C])

    def test_escape_desconocido(self):
        with self.assertRaises(AsmError):
            assemble('.string "\\q"')

    def test_sin_comillas(self):
        with self.assertRaises(AsmError):
            assemble('.string hola')


class LabelArithmeticTest(unittest.TestCase):

    def test_una_directiva_desplaza_las_etiquetas_siguientes(self):
        """El fallo que esto evita: contar 4 bytes por linea pase lo que pase.

        `tabla` ocupa tres palabras, asi que `despues` cae en 0x10 y no en 0x08.
        """
        fuente = "\n".join([
            "    NOP",
            "tabla:",
            "    .word 1, 2, 3",
            "despues:",
            "    NOP",
        ])
        _, labels = first_pass(fuente)
        self.assertEqual(labels["tabla"], 4)
        self.assertEqual(labels["despues"], 16)

    def test_una_cadena_tambien(self):
        fuente = "\n".join([
            "mensaje:",
            '    .string "hola"',   # 4 + NUL = 5 -> 2 palabras
            "despues:",
            "    NOP",
        ])
        _, labels = first_pass(fuente)
        self.assertEqual(labels["despues"], 8)

    def test_movi_con_etiqueta_carga_su_direccion(self):
        fuente = "\n".join([
            "    MOVI R1, mensaje",
            "    HALT",
            "mensaje:",
            '    .string "hi"',
        ])
        palabras = assemble(fuente)
        # MOVI R1, imm16 -> el inmediato es 0x08, la direccion de `mensaje`.
        self.assertEqual(palabras[0] & 0xFFFF, 8)

    def test_una_etiqueta_demasiado_lejos_para_movi(self):
        """Mas alla de 32 KiB hay que usar MOVHI + ORI, y se dice."""
        fuente = ["    MOVI R1, lejos"] + ["    NOP"] * 9000 + ["lejos:", "    NOP"]
        with self.assertRaises(AsmError) as error:
            assemble("\n".join(fuente))
        self.assertIn("MOVI", str(error.exception))


class ShiftInmediatoTest(unittest.TestCase):
    """SHLI, SHRI y SARI: opcion B de propuesta-v0.2.md §4.2.

    No hay opcodes nuevos. Son SHL, SHR y SAR con el bit 10 del campo `extra`
    puesto y la cantidad en el campo Rb. El ensamblador es el unico sitio donde
    ese detalle se puede comprobar sin ejecutar nada, y es facil equivocarse de
    bit, asi que aqui se fijan los encodings enteros.
    """

    def test_encoding_completo(self):
        palabras = assemble("SHLI R1, R2, 5")
        # opcode 0x07, Rd=1, Ra=2, Rb=5, extra=0x400
        esperado = (0x07 << 26) | (1 << 21) | (2 << 16) | (5 << 11) | 0x400
        self.assertEqual(palabras[0], esperado)

    def test_los_tres_reusan_el_opcode_de_su_version_con_registro(self):
        inmediatas = assemble("SHLI R1, R2, 3\nSHRI R1, R2, 3\nSARI R1, R2, 3")
        registros = assemble("SHL R1, R2, R3\nSHR R1, R2, R3\nSAR R1, R2, R3")
        for inmediata, registro in zip(inmediatas, registros):
            # Mismo opcode y mismos campos; lo unico que cambia es el bit 10.
            self.assertEqual(inmediata >> 26, registro >> 26)
            self.assertEqual(inmediata ^ registro, 0x400)

    def test_los_bordes_de_la_cantidad(self):
        self.assertEqual(assemble("SHLI R1, R2, 0")[0] & 0xF800, 0)
        self.assertEqual((assemble("SHLI R1, R2, 31")[0] >> 11) & 0x1F, 31)

    def test_cantidad_fuera_de_rango(self):
        """32 no cabe en cinco bits y truncarla en silencio seria peor."""
        for cantidad in ("32", "-1", "100"):
            with self.assertRaises(AsmError) as error:
                assemble(f"SHLI R1, R2, {cantidad}")
            self.assertIn("0..31", str(error.exception))

    def test_extra_a_cero_salvo_el_bit_del_modo(self):
        for texto in ("SHLI R1, R2, 5", "SHRI R1, R2, 5", "SARI R1, R2, 5"):
            self.assertEqual(assemble(texto)[0] & 0x3FF, 0)

    def test_la_forma_con_registro_no_pone_el_bit(self):
        self.assertEqual(assemble("SHL R1, R2, R3")[0] & 0x7FF, 0)


class AluExtendidaTest(unittest.TestCase):
    """MULHI, DIVU, REM y REMU: las cuatro reservadas de 1.isa/isa.md §3."""

    def test_opcodes(self):
        esperados = {"MULHI": 0x0B, "DIVU": 0x0D, "REM": 0x0E, "REMU": 0x0F}
        for mnemonico, opcode in esperados.items():
            palabra = assemble(f"{mnemonico} R1, R2, R3")[0]
            self.assertEqual(palabra >> 26, opcode, mnemonico)
            # R-Type con `extra` a cero, que es lo que exige el decodificador.
            self.assertEqual(palabra & 0x7FF, 0, mnemonico)
            self.assertEqual((palabra >> 21) & 0x1F, 1)
            self.assertEqual((palabra >> 16) & 0x1F, 2)
            self.assertEqual((palabra >> 11) & 0x1F, 3)

    def test_exigen_tres_operandos(self):
        with self.assertRaises(AsmError):
            assemble("MULHI R1, R2")


if __name__ == "__main__":
    unittest.main()
