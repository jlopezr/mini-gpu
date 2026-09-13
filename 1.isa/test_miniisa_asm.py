"""Pruebas del ensamblador: directivas de datos y etiquetas como inmediato.

El resto del ensamblador se prueba de hecho en cada caso de `x.cpu-tests`, que
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


if __name__ == "__main__":
    unittest.main()
