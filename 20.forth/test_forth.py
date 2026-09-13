"""Ejecuta el interprete de Forth sobre el simulador funcional.

No hay placa de por medio: `SerialDevice` de `2.cpu-sim-func` es el mismo
dispositivo que `serial_port.v`, asi que lo que se comprueba aqui es el
programa, no el modelo. Cada prueba mete una linea por la cola de entrada y
mira lo que el interprete deja en la de salida.

    ..\\.venv\\Scripts\\python.exe -m unittest test_forth -v
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FORTH = Path(__file__).resolve().parent / "forth.asm"


def _load(name: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(name, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


sim = _load("minicpu_sim_forth", REPO / "2.cpu-sim-func" / "minicpu_sim.py")
asm = _load("miniisa_asm_forth", REPO / "1.isa" / "miniisa_asm.py")

PROGRAM = b"".join(
    struct.pack("<I", w) for w in asm.assemble(FORTH.read_text(encoding="utf-8")))


def run_forth(lineas: str, max_instructions: int = 4_000_000) -> str:
    """Alimenta `lineas` al interprete y devuelve todo lo que conteste.

    La cola del hardware son 64 bytes, asi que la entrada se va metiendo a
    trozos conforme el programa la consume: es lo mismo que hace `send_all` en
    el PC, y por eso las pruebas pueden ser mas largas que la cola.
    """
    serie = sim.SerialDevice(stdin=b"")
    cpu = sim.CPU(memory_size=2 * 1024 * 1024, serial=serie)
    cpu.load_program(PROGRAM)

    pendiente = lineas.encode("latin-1")
    salida = bytearray()

    for _ in range(max_instructions):
        if cpu.halted:
            break
        if pendiente:
            aceptados = serie.push(pendiente)
            pendiente = pendiente[aceptados:]
        salida += serie.pop(255)
        cpu.step()

    salida += serie.pop(255)
    if cpu.error:
        raise AssertionError(
            f"la CPU paro con error 0x{cpu.error_code:02x} en 0x{cpu.pc:08x}")
    return salida.decode("latin-1")


class ForthTest(unittest.TestCase):

    def responde(self, entrada: str) -> str:
        """Ejecuta `entrada` y devuelve la sesion entera.

        Incluye el banner, los prompts y el eco de lo escrito, asi que las
        comprobaciones buscan el resultado rodeado de saltos de linea --
        `"\\n5\\n"` y no `"5"`-- para no confundirlo con el eco de la propia
        linea que lo produjo.
        """
        return run_forth(entrada + "bye\n")

    def test_arranca_y_saluda(self):
        self.assertIn("MiniForth", run_forth("bye\n"))
        self.assertIn("ok>", run_forth("bye\n"))
        self.assertIn("adios", run_forth("bye\n"))

    def test_suma(self):
        self.assertIn("\n5\n", self.responde("2 3 + .\n"))

    def test_las_cuatro_operaciones(self):
        self.assertIn("\n7\n", self.responde("10 3 - .\n"))
        self.assertIn("\n42\n", self.responde("6 7 * .\n"))
        self.assertIn("\n5\n", self.responde("37 7 / .\n"))

    def test_negativos(self):
        self.assertIn("\n-5\n", self.responde("3 8 - .\n"))
        self.assertIn("\n-7\n", self.responde("7 neg .\n"))
        self.assertIn("\n-3\n", self.responde("-3 .\n"))

    def test_cero(self):
        """El cero no pasa por el bucle de digitos: tiene su propio camino."""
        self.assertIn("\n0\n", self.responde("0 .\n"))
        self.assertIn("\n0\n", self.responde("5 5 - .\n"))

    def test_orden_de_los_operandos(self):
        """`10 3 -` es 7, no -7: el de abajo menos el de arriba."""
        salida = self.responde("10 3 - .\n")
        self.assertIn("\n7\n", salida)
        self.assertNotIn("-7", salida)

    def test_pila(self):
        self.assertIn("\n4\n", self.responde("2 dup * .\n"))
        self.assertIn("\n1\n", self.responde("1 2 drop .\n"))
        # `1 2 swap` deja 2 1 con el 1 arriba; `drop` se lleva el 1.
        self.assertIn("\n2\n", self.responde("1 2 swap drop .\n"))
        self.assertIn("\n1\n", self.responde("1 2 swap .\n"))
        self.assertIn("\n1\n", self.responde("1 2 over drop drop .\n"))

    def test_punto_s_no_toca_la_pila(self):
        salida = self.responde("10 20 30 .s .s\n")
        self.assertEqual(salida.count("<3> 10 20 30"), 2)

    def test_punto_s_con_la_pila_vacia(self):
        self.assertIn("<0>", self.responde(".s\n"))

    def test_comparaciones(self):
        self.assertIn("\n-1\n", self.responde("2 2 = .\n"))
        self.assertIn("\n0\n", self.responde("2 3 = .\n"))
        self.assertIn("\n-1\n", self.responde("2 3 < .\n"))
        self.assertIn("\n0\n", self.responde("3 2 < .\n"))
        self.assertIn("\n-1\n", self.responde("3 2 > .\n"))

    def test_memoria(self):
        """`valor direccion !` y `direccion @`, sobre la RAM libre."""
        self.assertIn("\n1234\n", self.responde("1234 1052672 ! 1052672 @ .\n"))

    def test_mayusculas_y_minusculas(self):
        self.assertIn("\n4\n", self.responde("2 DUP * .\n"))
        self.assertIn("\n4\n", self.responde("2 Dup * .\n"))

    def test_varias_palabras_en_una_linea(self):
        self.assertIn("\n30\n", self.responde("1 2 3 4 5 + + + + 15 + .\n"))

    def test_varias_lineas(self):
        salida = self.responde("2 3 +\n4 *\n.\n")
        self.assertIn("\n20\n", salida)

    def test_palabra_desconocida(self):
        # Se reimprime lo que el usuario escribio, no la version en mayuscula
        # con la que se busco: leer `? PEPE` cuando has escrito `pepe` hace
        # dudar de si el interprete ha entendido otra cosa.
        salida = self.responde("pepe\n")
        self.assertIn("? pepe", salida)

    def test_la_linea_se_descarta_tras_un_error(self):
        """`pepe 5 .` no imprime el 5: la linea entera se abandona."""
        salida = self.responde("pepe 5 .\n")
        self.assertIn("? pepe", salida)
        self.assertNotIn("\n5\n", salida)

    def test_pila_vacia(self):
        self.assertIn("pila vacia", self.responde("+\n"))
        self.assertIn("pila vacia", self.responde("1 +\n"))
        self.assertIn("pila vacia", self.responde(".\n"))

    def test_division_por_cero_no_mata_el_interprete(self):
        """La CPU para con error terminal si divide entre cero, asi que el
        interprete lo comprueba antes. Si no, la sesion se acabaria ahi."""
        salida = self.responde("1 0 / 7 .\n")
        self.assertIn("division por cero", salida)
        # Y sigue vivo: la linea siguiente se atiende.
        salida = self.responde("1 0 /\n7 .\n")
        self.assertIn("\n7\n", salida)

    def test_el_guion_suelto_es_la_resta(self):
        """`-` es una palabra, no el principio de un numero.

        Asi que con la pila vacia lo que sale es el error de pila, no
        "palabra desconocida". Es lo correcto en Forth, y conviene fijarlo
        porque el parser de numeros tambien mira el guion."""
        self.assertIn("pila vacia", self.responde("-\n"))
        self.assertIn("\n-5\n", self.responde("-5 .\n"))
        self.assertIn("? -x", self.responde("-x\n"))

    def test_nombre_de_mas_de_cuatro_letras(self):
        """No cabe en el diccionario empaquetado, y se dice en vez de acertar
        por casualidad con los cuatro primeros caracteres."""
        salida = self.responde("dropit\n")
        self.assertIn("? dropit", salida)

    def test_numero_grande(self):
        self.assertIn("\n1000000\n", self.responde("1000 1000 * .\n"))


class CompilerTest(unittest.TestCase):
    """`:` y `;`: la otra mitad de un Forth."""

    def responde(self, entrada: str) -> str:
        return run_forth(entrada + "bye\n")

    def test_definir_y_usar(self):
        self.assertIn("\n25\n", self.responde(": cuad dup * ;\n5 cuad .\n"))

    def test_la_definicion_no_se_ejecuta_al_definirla(self):
        """Compilar `5 .` no debe imprimir nada hasta que se invoque."""
        salida = self.responde(": pito 5 . ;\n")
        self.assertNotIn("\n5\n", salida)
        salida = self.responde(": pito 5 . ;\npito\n")
        self.assertIn("\n5\n", salida)

    def test_numeros_dentro_de_una_definicion(self):
        """Van con LIT: no se apilan al compilar, sino al ejecutar."""
        self.assertIn("\n7\n", self.responde(": siete 3 4 + ;\nsiete .\n"))
        self.assertIn("\n-7\n", self.responde(": mneg -7 ;\nmneg .\n"))

    def test_una_definicion_llama_a_otra(self):
        """Aqui es donde hace falta la pila de retorno."""
        salida = self.responde(
            ": cuad dup * ;\n: cuarta cuad cuad ;\n3 cuarta .\n")
        self.assertIn("\n81\n", salida)

    def test_anidamiento_de_tres_niveles(self):
        salida = self.responde(
            ": a 1 + ;\n: b a a ;\n: c b b ;\n0 c .\n")
        self.assertIn("\n4\n", salida)

    def test_la_misma_palabra_varias_veces(self):
        salida = self.responde(": tres dup dup ;\n7 tres + + .\n")
        self.assertIn("\n21\n", salida)

    def test_redefinir_tapa_la_anterior(self):
        """El diccionario es una lista y las nuevas van por delante."""
        salida = self.responde(": dos 2 ;\n: dos 22 ;\ndos .\n")
        self.assertIn("\n22\n", salida)

    def test_redefinir_no_cambia_las_que_ya_la_usaban(self):
        """Se compilo un puntero a la entrada vieja, no una busqueda por
        nombre: `usa` sigue viendo la primera `dos`, como en Forth."""
        salida = self.responde(
            ": dos 2 ;\n: usa dos dos + ;\n: dos 22 ;\nusa .\n")
        self.assertIn("\n4\n", salida)

    def test_una_definicion_puede_usar_builtins_y_definidas(self):
        salida = self.responde(": doble dup + ;\n: cuadruple doble doble ;\n5 cuadruple .\n")
        self.assertIn("\n20\n", salida)

    def test_definicion_en_varias_lineas(self):
        """El modo compilacion sobrevive al salto de linea."""
        salida = self.responde(": cuad\ndup *\n;\n6 cuad .\n")
        self.assertIn("\n36\n", salida)

    def test_words_ensena_lo_definido(self):
        salida = self.responde(": pepe 1 ;\nwords\n")
        self.assertIn("PEPE", salida)
        self.assertIn("DUP", salida)

    def test_punto_y_coma_es_inmediata(self):
        """Si no lo fuera se compilaria dentro de la definicion y el modo
        compilacion no se apagaria nunca: la linea siguiente se tragaria."""
        salida = self.responde(": uno 1 ;\n9 .\n")
        self.assertIn("\n9\n", salida)

    def test_un_error_dentro_de_una_definicion_la_deshace(self):
        """Sin esto queda una entrada cuyo cuerpo no termina en cero, y el
        interprete interno se iria a recorrer memoria al invocarla."""
        salida = self.responde(": mala 1 pepe 2 ;\nwords\n")
        self.assertIn("? pepe", salida)
        self.assertNotIn("MALA", salida)
        # Y el interprete sigue usable.
        salida = self.responde(": mala 1 pepe 2 ;\n3 4 + .\n")
        self.assertIn("\n7\n", salida)

    def test_tras_un_error_vuelve_a_modo_interprete(self):
        salida = self.responde(": mala pepe ;\n5 .\n")
        self.assertIn("\n5\n", salida)

    def test_una_definicion_con_pila_vacia_avisa_al_ejecutarse(self):
        """El error es de ejecucion, no de compilacion: al definirla no se
        comprueba nada, que es lo normal en Forth."""
        salida = self.responde(": rompe + ;\nrompe\n")
        self.assertIn("pila vacia", salida)
        self.assertNotIn("? ", salida)


class ControlFlowTest(unittest.TestCase):
    """IF/ELSE/THEN y los bucles: palabras inmediatas que emiten saltos."""

    def responde(self, entrada: str) -> str:
        return run_forth(entrada + "bye\n")

    def test_if_then_verdadero(self):
        salida = self.responde(": t 1 = if 42 . then ;\n1 t\n")
        self.assertIn("\n42\n", salida)

    def test_if_then_falso(self):
        salida = self.responde(": t 1 = if 42 . then ;\n9 t\n")
        self.assertNotIn("\n42\n", salida)

    def test_if_else_then(self):
        fuente = ": signo 0 < if -1 . else 1 . then ;\n"
        self.assertIn("\n-1\n", self.responde(fuente + "-5 signo\n"))
        self.assertIn("\n1\n", self.responde(fuente + "5 signo\n"))

    def test_if_anidados(self):
        fuente = (": clas dup 0 < if drop -1 . else 0 = if 0 . else 1 . then"
                  " then ;\n")
        self.assertIn("\n-1\n", self.responde(fuente + "-7 clas\n"))
        self.assertIn("\n0\n", self.responde(fuente + "0 clas\n"))
        self.assertIn("\n1\n", self.responde(fuente + "7 clas\n"))

    def test_begin_until(self):
        """Cuenta atras desde 5: imprime 5 4 3 2 1."""
        fuente = ": baja begin dup . 1 - dup 0 = until drop ;\n5 baja\n"
        salida = self.responde(fuente)
        for n in (5, 4, 3, 2, 1):
            self.assertIn(f"\n{n}\n", salida)
        self.assertNotIn("\n0\n", salida)

    def test_begin_while_repeat(self):
        fuente = ": baja begin dup 0 > while dup . 1 - repeat drop ;\n3 baja\n"
        salida = self.responde(fuente)
        for n in (3, 2, 1):
            self.assertIn(f"\n{n}\n", salida)
        self.assertNotIn("\n0\n", salida)

    def test_while_no_entra_si_la_condicion_es_falsa_de_entrada(self):
        fuente = ": baja begin dup 0 > while dup . 1 - repeat drop ;\n0 baja\n"
        salida = self.responde(fuente)
        self.assertNotIn("\n0\n", salida)

    def test_un_bucle_que_acumula(self):
        """Suma 1..5 y deja 15. Es el bucle util de verdad.

        El acumulador va en memoria (`0x00102000`) y no en la pila porque sin
        `PICK` ni `TUCK` no hay forma comoda de llegar al tercer elemento. Esa
        incomodidad es informacion: dice que faltan palabras de pila.
        """
        fuente = (": suma 0 1052672 ! 5"
                  " begin dup 0 > while"
                  " dup 1052672 @ + 1052672 !"
                  " 1 - repeat drop"
                  " 1052672 @ . ;\nsuma\n")
        self.assertIn("\n15\n", self.responde(fuente))

    def test_again_y_bye_para_el_bucle(self):
        """AGAIN no tiene salida; se sale parando la CPU."""
        salida = run_forth(": eterno begin 7 . bye again ;\neterno\n")
        self.assertIn("\n7\n", salida)
        self.assertIn("adios", salida)

    def test_control_fuera_de_una_definicion(self):
        """Compilar saltos en modo interprete no tiene sentido: se rechaza."""
        for palabra in ("if", "then", "begin", "until", "while", "repeat"):
            with self.subTest(palabra=palabra):
                self.assertIn("solo dentro de :", self.responde(palabra + "\n"))

    def test_then_sin_if(self):
        """La pila de compilacion esta vacia: se avisa en vez de escribir en
        una direccion cualquiera."""
        salida = self.responde(": mala then ;\n")
        self.assertIn("control de flujo", salida)

    def test_el_interprete_sobrevive_a_un_control_descuadrado(self):
        salida = self.responde(": mala then ;\n3 4 + .\n")
        self.assertIn("\n7\n", salida)


class DefiningWordsTest(unittest.TestCase):
    """CREATE y DOES>: palabras que definen palabras.

    Lo que se comprueba aqui no es una funcionalidad mas, sino la propiedad que
    separa a Forth de una calculadora con nombres: `CONSTANT` y `VARIABLE` no
    estan en el interprete, se escriben EN Forth desde la consola.
    """

    def responde(self, entrada: str) -> str:
        return run_forth(entrada + "bye\n")

    def test_create_apila_la_direccion_de_sus_datos(self):
        salida = self.responde("create x  x x = .\n")
        self.assertIn("\n-1\n", salida)   # la misma direccion las dos veces

    def test_create_con_datos(self):
        salida = self.responde("create tabla 10 , 20 , 30 ,\n"
                               "tabla @ .\ntabla 4 + @ .\ntabla 8 + @ .\n")
        for n in (10, 20, 30):
            self.assertIn(f"\n{n}\n", salida)

    def test_constant_escrita_en_forth(self):
        salida = self.responde(": constant create , does> @ ;\n"
                               "5 constant cinco\ncinco .\n")
        self.assertIn("\n5\n", salida)

    def test_constant_se_puede_usar_varias_veces(self):
        salida = self.responde(": constant create , does> @ ;\n"
                               "5 constant cinco\ncinco cinco + .\n")
        self.assertIn("\n10\n", salida)

    def test_varias_constantes_independientes(self):
        """Cada palabra creada tiene SU zona de datos."""
        salida = self.responde(": constant create , does> @ ;\n"
                               "3 constant tres\n7 constant siete\n"
                               "tres . siete . tres siete + .\n")
        self.assertIn("\n3\n", salida)
        self.assertIn("\n7\n", salida)
        self.assertIn("\n10\n", salida)

    def test_variable_escrita_en_forth(self):
        salida = self.responde(": variable create 0 , ;\n"
                               "variable v\n7 v !\nv @ .\n")
        self.assertIn("\n7\n", salida)

    def test_variable_arranca_a_cero(self):
        salida = self.responde(": variable create 0 , ;\nvariable v\nv @ .\n")
        self.assertIn("\n0\n", salida)

    def test_array_con_cells_y_allot(self):
        salida = self.responde(
            ": array create cells allot does> swap cells + ;\n"
            "5 array v\n11 0 v !\n22 1 v !\n33 2 v !\n"
            "0 v @ . 1 v @ . 2 v @ .\n")
        for n in (11, 22, 33):
            self.assertIn(f"\n{n}\n", salida)

    def test_una_definidora_dentro_de_otra_definicion(self):
        """Una palabra creada invocada desde una definicion compilada pasa por
        `inner_created`, que es un camino distinto de `run_created`."""
        salida = self.responde(": constant create , does> @ ;\n"
                               "6 constant seis\n"
                               ": doble seis seis + ;\ndoble .\n")
        self.assertIn("\n12\n", salida)

    def test_create_pelado_dentro_de_una_definicion(self):
        """Sin DOES>, la palabra creada solo apila su direccion, y eso tambien
        tiene que funcionar desde dentro de una definicion."""
        salida = self.responde("create c 42 ,\n: leer c @ ;\nleer .\n")
        self.assertIn("\n42\n", salida)

    def test_lo_de_despues_de_does_no_se_ejecuta_al_definir(self):
        """`DOES> @` no debe leer nada mientras se define CONSTANT."""
        salida = self.responde(": constant create , does> @ ;\n9 .\n")
        self.assertIn("\n9\n", salida)
        self.assertNotIn("pila vacia", salida)

    def test_words_lista_lo_creado(self):
        salida = self.responde("create pepe\nwords\n")
        self.assertIn("PEPE", salida)

    def test_comma_con_la_pila_vacia(self):
        self.assertIn("pila vacia", self.responde(",\n"))


class StackWordsTest(unittest.TestCase):

    def responde(self, entrada: str) -> str:
        return run_forth(entrada + "bye\n")

    def test_rot(self):
        """a b c -- b c a. El orden importa y es facil dejarlo al reves."""
        salida = self.responde("1 2 3 rot .s\n")
        self.assertIn("<3> 2 3 1", salida)

    def test_nip_y_tuck(self):
        self.assertIn("<1> 2", self.responde("1 2 nip .s\n"))
        self.assertIn("<3> 2 1 2", self.responde("1 2 tuck .s\n"))

    def test_dos_dup_y_dos_drop(self):
        self.assertIn("<4> 1 2 1 2", self.responde("1 2 2dup .s\n"))
        self.assertIn("<1> 1", self.responde("1 2 3 2drop .s\n"))

    def test_depth(self):
        self.assertIn("\n0\n", self.responde("depth .\n"))
        self.assertIn("\n3\n", self.responde("7 7 7 depth .\n"))

    def test_pick(self):
        """0 PICK es DUP; n PICK cuenta desde arriba."""
        self.assertIn("<4> 1 2 3 3", self.responde("1 2 3 0 pick .s\n"))
        self.assertIn("<4> 1 2 3 1", self.responde("1 2 3 2 pick .s\n"))

    def test_pick_mas_hondo_que_la_pila(self):
        self.assertIn("pila vacia", self.responde("1 2 9 pick\n"))


class ArithmeticWordsTest(unittest.TestCase):

    def responde(self, entrada: str) -> str:
        return run_forth(entrada + "bye\n")

    def test_mod(self):
        self.assertIn("\n2\n", self.responde("17 5 mod .\n"))
        self.assertIn("\n0\n", self.responde("20 5 mod .\n"))

    def test_mod_por_cero_no_mata_la_sesion(self):
        salida = self.responde("1 0 mod\n7 .\n")
        self.assertIn("division por cero", salida)
        self.assertIn("\n7\n", salida)

    def test_abs_min_max(self):
        self.assertIn("\n9\n", self.responde("-9 abs .\n"))
        self.assertIn("\n9\n", self.responde("9 abs .\n"))
        self.assertIn("\n3\n", self.responde("3 9 min .\n"))
        self.assertIn("\n9\n", self.responde("3 9 max .\n"))
        self.assertIn("\n-9\n", self.responde("-9 3 min .\n"))

    def test_incrementos(self):
        self.assertIn("\n6\n", self.responde("5 1+ .\n"))
        self.assertIn("\n4\n", self.responde("5 1- .\n"))

    def test_logica(self):
        self.assertIn("\n8\n", self.responde("12 10 and .\n"))
        self.assertIn("\n14\n", self.responde("12 10 or .\n"))
        self.assertIn("\n6\n", self.responde("12 10 xor .\n"))
        self.assertIn("\n-1\n", self.responde("0 invert .\n"))

    def test_comparaciones_con_cero(self):
        self.assertIn("\n-1\n", self.responde("0 0= .\n"))
        self.assertIn("\n0\n", self.responde("5 0= .\n"))
        self.assertIn("\n-1\n", self.responde("-5 0< .\n"))
        self.assertIn("\n0\n", self.responde("5 0< .\n"))


class TextAndBaseTest(unittest.TestCase):

    def responde(self, entrada: str) -> str:
        return run_forth(entrada + "bye\n")

    def test_emit_y_space(self):
        salida = self.responde("65 emit 66 emit space 67 emit cr\n")
        self.assertIn("AB C\n", salida)

    def test_dot_quote_interpretando(self):
        self.assertIn("hola mundo", self.responde('." hola mundo" cr\n'))

    def test_dot_quote_compilando(self):
        """La cadena va incrustada en el cuerpo, detras de una primitiva."""
        salida = self.responde(': saluda ." hola" cr ;\nsaluda\nsaluda\n')
        self.assertEqual(salida.count("hola"), 3)   # el eco de la definicion + 2

    def test_dot_quote_no_rompe_lo_que_sigue(self):
        """Tras la cadena, el cuerpo sigue alineado a palabra.

        El `cr` va en medio porque `."` no imprime salto de linea: sin el, la
        salida seria `abc42` y la comprobacion no distinguiria el numero del
        texto.
        """
        salida = self.responde(': x ." abc" cr 42 . ;\nx\n')
        self.assertIn("abc", salida)
        self.assertIn("\n42\n", salida)

    def test_dot_quote_de_longitudes_distintas(self):
        """El relleno hasta la palabra es donde se rompe un `."` mal hecho.

        Con 1, 2, 3, 4 y 5 caracteres se cubren todos los restos de la
        division por cuatro, que es donde un calculo de alineacion mal hecho
        deja el cuerpo desplazado y la palabra siguiente se lee de basura.
        """
        for texto in ("a", "ab", "abc", "abcd", "abcde"):
            with self.subTest(texto=texto):
                salida = self.responde(f': x ." {texto}" cr 7 . ;\nx\n')
                self.assertIn(texto, salida)
                self.assertIn("\n7\n", salida)

    def test_hex_y_decimal(self):
        self.assertIn("\nFF\n", self.responde("255 hex . decimal\n"))
        self.assertIn("\n255\n", self.responde("hex ff decimal .\n"))

    def test_en_decimal_una_letra_no_es_un_digito(self):
        self.assertIn("? 1a", self.responde("decimal 1a\n"))

    def test_hex_acepta_minusculas(self):
        self.assertIn("\n255\n", self.responde("hex ff decimal .\n"))
        self.assertIn("\n255\n", self.responde("hex FF decimal .\n"))


class ExitRecurseTest(unittest.TestCase):

    def responde(self, entrada: str) -> str:
        return run_forth(entrada + "bye\n")

    def test_exit_sale_de_la_definicion(self):
        salida = self.responde(": p 5 exit 99 ;\np .\n")
        self.assertIn("\n5\n", salida)
        self.assertNotIn("\n99\n", salida)

    def test_exit_desde_dentro_de_un_if(self):
        fuente = ": p dup 0 < if drop -1 exit then drop 1 ;\n"
        self.assertIn("\n-1\n", self.responde(fuente + "-5 p .\n"))
        self.assertIn("\n1\n", self.responde(fuente + "5 p .\n"))

    def test_exit_vuelve_solo_un_nivel(self):
        """Una definicion que llama a otra que hace EXIT sigue ejecutandose."""
        salida = self.responde(": a 1 . exit 2 . ;\n: b a 3 . ;\nb\n")
        self.assertIn("\n1\n", salida)
        self.assertIn("\n3\n", salida)
        self.assertNotIn("\n2\n", salida)

    def test_recurse(self):
        salida = self.responde(": cd dup 0 > if dup . 1- recurse then ;\n4 cd\n")
        for n in (4, 3, 2, 1):
            self.assertIn(f"\n{n}\n", salida)

    def test_recurse_fuera_de_una_definicion(self):
        self.assertIn("solo dentro de :", self.responde("recurse\n"))


if __name__ == "__main__":
    unittest.main()
