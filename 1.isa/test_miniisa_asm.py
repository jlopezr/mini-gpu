"""Pruebas del ensamblador: directivas de datos y etiquetas como inmediato.

El resto del ensamblador se prueba de hecho en cada caso de `x.tests`, que
ensambla programas reales. Lo que se fija aqui es lo que ese camino NO ejercita:
las directivas `.word` y `.string`, y la aritmetica de etiquetas alrededor de
ellas, que es donde un error deja todas las etiquetas posteriores mal sin que
nada se queje.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
        _, labels, _ = first_pass(fuente)
        self.assertEqual(labels["tabla"], 4)
        self.assertEqual(labels["despues"], 16)

    def test_una_cadena_tambien(self):
        fuente = "\n".join([
            "mensaje:",
            '    .string "hola"',   # 4 + NUL = 5 -> 2 palabras
            "despues:",
            "    NOP",
        ])
        _, labels, _ = first_pass(fuente)
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


class CompareTest(unittest.TestCase):
    """SLT y SLTU: comparaciones materializadas, capability `compare`."""

    def test_opcodes(self):
        esperados = {"SLT": 0x26, "SLTU": 0x27}
        for mnemonico, opcode in esperados.items():
            palabra = assemble(f"{mnemonico} R1, R2, R3")[0]
            self.assertEqual(palabra >> 26, opcode, mnemonico)
            # R-Type con `extra` a cero, igual que ADD.
            self.assertEqual(palabra & 0x7FF, 0, mnemonico)
            self.assertEqual((palabra >> 21) & 0x1F, 1)
            self.assertEqual((palabra >> 16) & 0x1F, 2)
            self.assertEqual((palabra >> 11) & 0x1F, 3)

    def test_exigen_tres_operandos(self):
        with self.assertRaises(AsmError):
            assemble("SLT R1, R2")


class EtiquetaLocalTest(unittest.TestCase):
    """Etiquetas `@x`, locales a la ultima global.

    Existen por los `.include`: sin ellas `drawline.inc` se apropiaba de nueve
    nombres globales, ocho de los cuales son saltos internos.
    """

    def test_el_mismo_nombre_en_dos_ambitos(self):
        """Lo que justifica la funcion: dos rutinas con su propio `@loop`."""
        palabras = assemble(
            "uno:\n"
            "@loop:\n"
            "    ADD R1, R2, R3\n"
            "    BNE R1, R0, @loop\n"
            "dos:\n"
            "@loop:\n"
            "    SUB R1, R2, R3\n"
            "    BNE R1, R0, @loop\n"
        )
        self.assertEqual(len(palabras), 4)
        # Cada BNE salta a SU @loop, no al del otro ambito. El offset es
        # relativo a PC+4 y va en palabras, asi que volver a la instruccion
        # de arriba son -2, no -1.
        for indice in (1, 3):
            self.assertEqual(palabras[indice] & 0xFFFF, 0xFFFE)

    def test_sin_etiqueta_global_antes(self):
        with self.assertRaises(AsmError) as caja:
            assemble("@x:\n    HALT\n")
        self.assertIn("sin ninguna etiqueta global", str(caja.exception))

    def test_local_no_definida_se_explica_con_su_nombre(self):
        """El nombre interno es `a@no_existe`, que no lo escribio nadie."""
        with self.assertRaises(AsmError) as caja:
            assemble("a:\n    BRA @no_existe\n")
        mensaje = str(caja.exception)
        self.assertIn("etiqueta no definida", mensaje)
        self.assertIn("@no_existe", mensaje)
        self.assertIn("local de a", mensaje)

    def test_una_local_no_abre_ambito(self):
        """Si `@a` abriera ambito, `@b` perteneceria a `@a` y no a `g`."""
        palabras = assemble(
            "g:\n@a:\n    NOP\n@b:\n    NOP\n    BRA @a\n"
        )
        self.assertEqual(len(palabras), 3)
        self.assertEqual(palabras[2] & 0xFFFF, 0xFFFD)   # tres atras

    def test_arroba_dentro_de_una_cadena_no_es_etiqueta(self):
        palabras = assemble('g:\n    .string "a@b"\n')
        self.assertEqual(len(palabras), 1)               # 4 bytes: a @ b NUL

    def test_no_choca_con_una_global_del_mismo_nombre(self):
        palabras = assemble(
            "loop:\n    NOP\n"
            "g:\n@loop:\n    NOP\n    BRA @loop\n    BRA loop\n"
        )
        self.assertEqual(len(palabras), 4)
        self.assertEqual(palabras[2] & 0xFFFF, 0xFFFE)   # @loop, la de arriba
        self.assertEqual(palabras[3] & 0xFFFF, 0xFFFC)   # loop global, cuatro


class IncludeTest(unittest.TestCase):
    """`.include`, que existe porque `drawline` estaba copiado en tres sitios.

    Sin espacios de nombres, lo que hay que vigilar no es que la inclusion
    funcione --eso es pegar texto-- sino que los fallos se expliquen: quien
    define un label dos veces, que fichero falta, y donde esta el ciclo.
    """

    def escribir(self, carpeta, nombre, texto):
        ruta = Path(carpeta) / nombre
        ruta.write_text(texto, encoding="utf-8")
        return ruta

    def test_incluye_desde_la_carpeta_del_fuente(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(tmp, "trozo.inc", "sumar:\n    ADD R1, R2, R3\n    RET\n")
            programa = 'JAL R31, sumar\nHALT\n.include "trozo.inc"\n'
            palabras = assemble(programa, Path(tmp), "prog.asm")
        # JAL, HALT, ADD, RET
        self.assertEqual(len(palabras), 4)

    def test_carpeta_de_busqueda_adicional(self):
        """El `-I`: el fichero no esta junto al fuente sino en la biblioteca."""
        with tempfile.TemporaryDirectory() as fuente, \
                tempfile.TemporaryDirectory() as lib:
            self.escribir(lib, "trozo.inc", "    NOP\n")
            palabras = assemble('HALT\n.include "trozo.inc"\n',
                                Path(fuente), "prog.asm", (Path(lib),))
        self.assertEqual(len(palabras), 2)

    def test_la_carpeta_del_fuente_gana_al_include_dir(self):
        """Un trozo local con el mismo nombre tiene que ganar al compartido.

        Si no, cambiar la biblioteca romperia programas ajenos en silencio.
        """
        with tempfile.TemporaryDirectory() as fuente, \
                tempfile.TemporaryDirectory() as lib:
            self.escribir(fuente, "trozo.inc", "    NOP\n    NOP\n")
            self.escribir(lib, "trozo.inc", "    NOP\n")
            palabras = assemble('.include "trozo.inc"\n',
                                Path(fuente), "prog.asm", (Path(lib),))
        self.assertEqual(len(palabras), 2)

    def test_include_anidado_resuelve_desde_su_propia_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "sub"
            sub.mkdir()
            self.escribir(sub, "hoja.inc", "    NOP\n")
            self.escribir(sub, "rama.inc", '    NOP\n.include "hoja.inc"\n')
            palabras = assemble('.include "sub/rama.inc"\n', Path(tmp), "prog.asm")
        self.assertEqual(len(palabras), 2)

    def test_label_duplicado_dice_los_dos_sitios(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(tmp, "trozo.inc", "sumar:\n    RET\n")
            with self.assertRaises(AsmError) as caja:
                assemble('sumar:\n    RET\n.include "trozo.inc"\n',
                         Path(tmp), "prog.asm")
        mensaje = str(caja.exception)
        self.assertIn("sumar", mensaje)
        self.assertIn("trozo.inc", mensaje)      # donde se choca
        self.assertIn("prog.asm", mensaje)       # donde estaba ya definido

    def test_ciclo_detectado(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(tmp, "a.inc", '.include "b.inc"\n')
            self.escribir(tmp, "b.inc", '.include "a.inc"\n')
            with self.assertRaises(AsmError) as caja:
                assemble('.include "a.inc"\n', Path(tmp), "prog.asm")
        self.assertIn("circular", str(caja.exception))

    def test_fichero_que_falta_dice_donde_se_ha_mirado(self):
        with tempfile.TemporaryDirectory() as fuente, \
                tempfile.TemporaryDirectory() as lib:
            with self.assertRaises(AsmError) as caja:
                assemble('.include "no_existe.inc"\n',
                         Path(fuente), "prog.asm", (Path(lib),))
        mensaje = str(caja.exception)
        self.assertIn("no_existe.inc", mensaje)
        self.assertIn(lib, mensaje)

    def test_sin_carpeta_base_el_error_lo_explica(self):
        """Los simuladores ensamblan cadenas sueltas: ahi no hay desde donde."""
        with self.assertRaises(AsmError) as caja:
            assemble('.include "trozo.inc"\n')
        self.assertIn("relativa", str(caja.exception))

    def test_ruta_sin_comillas(self):
        with self.assertRaises(AsmError):
            assemble(".include trozo.inc\n", Path("."), "prog.asm")

    def test_once_evita_la_segunda_inclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(tmp, "trozo.inc", "    .once\nsumar:\n    RET\n")
            palabras = assemble(
                'HALT\n.include "trozo.inc"\n.include "trozo.inc"\n',
                Path(tmp), "prog.asm")
        self.assertEqual(len(palabras), 2)      # HALT + RET, no RET dos veces

    def test_sin_once_la_segunda_inclusion_choca(self):
        """El contraste del anterior: `.once` es opt-in, no el comportamiento.

        Incluir dos veces a proposito es legitimo --una tabla que se quiere
        emitir dos veces-- asi que `.include` no deduplica por su cuenta.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(tmp, "trozo.inc", "sumar:\n    RET\n")
            with self.assertRaises(AsmError) as caja:
                assemble('.include "trozo.inc"\n.include "trozo.inc"\n',
                         Path(tmp), "prog.asm")
        self.assertIn("duplicado", str(caja.exception))

    def test_once_en_diamante(self):
        """El caso que motiva `.once`: A y B piden C, y el programa pide los dos.

        Es la forma que tiene drawline.inc de arrastrar putpixel.inc sin
        chocar con el programa que tambien lo incluye.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(tmp, "c.inc", "    .once\nhoja:\n    RET\n")
            self.escribir(tmp, "a.inc", '.include "c.inc"\na:\n    RET\n')
            self.escribir(tmp, "b.inc", '.include "c.inc"\nb:\n    RET\n')
            palabras = assemble('HALT\n.include "a.inc"\n.include "b.inc"\n',
                                Path(tmp), "prog.asm")
        # HALT + hoja + a + b: la hoja una sola vez
        self.assertEqual(len(palabras), 4)

    def test_once_en_el_principal_no_hace_nada(self):
        """Un .asm puede querer ensamblarse suelto Y ser incluido por otro, asi
        que marcarlo no puede impedir lo primero."""
        palabras = assemble("    .once\n    HALT\n")
        self.assertEqual(len(palabras), 1)

    def test_las_secciones_del_incluido_cuentan(self):
        """Un .inc que mete datos en .rodata no descoloca el .text de quien lo
        incluye: las secciones se reordenan al final, como siempre."""
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(tmp, "tabla.inc",
                          "    .rodata\ntabla:\n    .word 1, 2\n    .text\n")
            palabras = assemble(
                'MOVI R1, tabla\nHALT\n.include "tabla.inc"\n',
                Path(tmp), "prog.asm")
        # dos instrucciones y dos palabras de datos, y la tabla detras del texto
        self.assertEqual(len(palabras), 4)
        self.assertEqual(palabras[0] & 0xFFFF, 8)


if __name__ == "__main__":
    unittest.main()
