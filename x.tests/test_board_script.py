"""`tools/board_script.py`: los guiones de `monitor.py input --script`, sin placa.

Se usa la misma placa falsa que en `test_board_input.py` (FPGA más aplicación con
puntero recortado y pantalla de texto). Lo que se comprueba:

  - la interpretación y los errores, todos detectados al cargar el guion;
  - que las acciones de teclado y ratón mandan lo que mandaría el simulador, en el
    orden de §25.11 (presencia primero al conectar, al final al desconectar);
  - `click` y `moveto` caen en la celda pedida, estuviera donde estuviera el puntero;
  - `expect` y `wait`: pasan, o paran el guion y dicen qué esperaban y qué vieron.
"""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "x.tests"))

from test_board_input import FakeBoard  # noqa: E402

from tools import board_script  # noqa: E402
from tools.board_script import ScriptError, ScriptFailure  # noqa: E402
from tools.sim_devices import InputDevice as D  # noqa: E402

H, A, B = 0x0B, 0x04, 0x05


def run(text, fake=None, **kwargs):
    fake = fake or FakeBoard()
    steps = board_script.parse(text)
    board_script.check(steps)
    checks = board_script.run(fake, steps, settle=0, log=lambda line: None, **kwargs)
    return fake, checks


class ParseTest(unittest.TestCase):
    def assertScriptError(self, text, fragment):
        with self.assertRaises(ScriptError) as caught:
            board_script.load_text(text) if hasattr(board_script, "load_text") else \
                board_script.check(board_script.parse(text))
        self.assertIn(fragment, str(caught.exception))

    def test_los_instantes_son_milisegundos_absolutos_o_relativos(self):
        steps = board_script.parse(
            "@10 keyboard connect\n+90 key press A\n@500 mouse connect\n")
        self.assertEqual([(s.at, s.line) for s in steps],
                         [(10, 1), (100, 2), (100, 2), (500, 3)])

    def test_sin_instante_o_hacia_atras_no_vale(self):
        self.assertScriptError("keyboard connect", "empieza por @N o +N")
        self.assertScriptError("@100 keyboard connect\n@50 keyboard disconnect",
                               "anterior")

    def test_acciones_y_argumentos_mal_escritos_dicen_la_linea(self):
        self.assertScriptError("@0 teleport 1 2", "línea 1")
        self.assertScriptError("@0 click 1", "click admite")
        self.assertScriptError("@0 click 80 0", "fuera de la pantalla")
        self.assertScriptError("@0 click 0 30", "fuera de la pantalla")
        self.assertScriptError("@0 expect row 99 contains x", "no existe")
        self.assertScriptError("@0 expect screen is x", "una fila entera")
        self.assertScriptError("@0 expect row 3 contains", "se espera")
        self.assertScriptError("@0 expect row 3 contains a b", "sobra")

    def test_se_detecta_antes_de_empezar_una_tecla_sin_teclado(self):
        self.assertScriptError("@0 key press A", "teclado no presente")
        self.assertScriptError("@0 click 1 1", "ratón no presente")

    def test_un_texto_puede_llevar_almohadilla_y_comentarios_al_final(self):
        (step,) = board_script.parse('@0 expect row 3 contains "a # b"   # nota\n')
        self.assertEqual(step.line, 1)


class DeviceActionTest(unittest.TestCase):
    def test_teclas_y_presencia_en_el_orden_del_contrato(self):
        fake, _ = run('@0 keyboard connect\n+10 type "ab"\n+10 keyboard disconnect\n')
        presences = [c for c in fake.commands if c[0] == "presence"]
        # Vacia al empezar, el teclado al conectar, vacia al desconectar.
        self.assertEqual(presences[0], ("presence", False, False))
        self.assertEqual(presences[1], ("presence", True, False))
        self.assertEqual(presences[-1], ("presence", False, False))
        self.assertEqual(fake.keys_down, [A, B])
        self.assertEqual(fake.device.keys, 0)

    def test_conectar_con_teclas_pulsadas_las_manda_despues_de_la_presencia(self):
        fake, _ = run("@0 keyboard connect A\n")
        names = [c[0] for c in fake.commands]
        self.assertLess(names.index("presence"), len(names))
        first_events = next(i for i, c in enumerate(fake.commands)
                            if c[0] == "events" and c[1])
        key_presence = next(i for i, c in enumerate(fake.commands)
                            if c == ("presence", True, False))
        self.assertLess(key_presence, first_events)
        self.assertEqual(fake.keys_down, [A])

    def test_al_terminar_se_suelta_todo_aunque_el_guion_no_lo_haga(self):
        fake, _ = run("@0 keyboard connect\n+0 mouse connect\n+0 key down A\n"
                      "+0 mouse button left down\n")
        self.assertEqual(fake.device.keys, 0)
        self.assertEqual(fake.device.mouse_buttons, 0)
        self.assertFalse(fake.device.keyboard_present)
        self.assertFalse(fake.device.mouse_present)
        # Y la aplicacion los ve soltarse: no solo se borra el estado.
        self.assertEqual(fake.keys_up, [A])
        self.assertEqual(fake.buttons_up, [0])

    def test_los_instantes_se_respetan(self):
        start = time.monotonic()
        run("@0 keyboard connect\n+250 key press A\n")
        self.assertGreaterEqual(time.monotonic() - start, 0.24)


class MouseTest(unittest.TestCase):
    def test_click_cae_en_la_celda_aunque_el_puntero_estuviera_en_otro_sitio(self):
        for start in [(500, 100), (0, 0), (639, 479)]:
            fake, _ = run("@0 mouse connect\n+0 click 53 6\n+0 click 0 0 right\n",
                          fake=FakeBoard(pointer=start))
            self.assertEqual(fake.clicks, [((53, 6), 0), ((0, 0), 1)], start)

    def test_moveto_mueve_sin_pulsar(self):
        fake, _ = run("@0 mouse connect\n+0 moveto 40 15\n")
        self.assertEqual(fake.clicks, [])
        self.assertEqual(tuple(fake.pointer), (40 * 8 + 4, 15 * 16 + 8))

    def test_el_movimiento_relativo_del_simulador_tambien_vale(self):
        fake, _ = run("@0 mouse connect\n+0 mouse move 10 -5\n+0 mouse button left click\n")
        self.assertEqual(tuple(fake.pointer), (330, 235))
        self.assertEqual(fake.clicks, [((41, 14), 0)])


class ScreenCheckTest(unittest.TestCase):
    def fake_with(self, row, text, column=0):
        fake = FakeBoard()
        for i, ch in enumerate(text):
            fake.text[(column + i, row)] = ch
        return fake

    def test_expect_pasa(self):
        fake = self.fake_with(13, "hola mundo", column=4)
        _, checks = run('@0 expect row 13 contains "hola"\n'
                        '+0 expect row 13 is "    hola mundo"\n'
                        '+0 expect row 13 absent "adios"\n'
                        '+0 expect screen contains "mundo"\n'
                        '+0 expect screen absent "adios"\n', fake=fake)
        self.assertEqual(checks, 5)

    def test_expect_que_falla_para_el_guion_y_dice_la_linea_y_lo_visto(self):
        fake = self.fake_with(13, "hola")
        with self.assertRaises(ScriptFailure) as caught:
            run('@0 keyboard connect\n+0 expect row 13 contains "adios"\n', fake=fake)
        mensaje = str(caught.exception)
        self.assertIn("línea 2", mensaje)
        self.assertIn("la fila 13 contenga 'adios'", mensaje)
        self.assertIn("hola", mensaje)

    def test_un_fallo_no_se_salta_la_limpieza(self):
        fake = self.fake_with(13, "x")
        with self.assertRaises(ScriptFailure):
            run('@0 keyboard connect\n+0 key down A\n+0 expect row 13 contains "y"\n',
                fake=fake)
        self.assertEqual(fake.device.keys, 0)
        self.assertEqual(fake.commands[-1], ("presence", False, False))

    def test_wait_espera_a_que_aparezca_y_agota_el_tiempo_si_no(self):
        fake = self.fake_with(5, "listo")
        run('@0 wait row 5 contains "listo" 200\n', fake=fake)
        with self.assertRaises(ScriptFailure) as caught:
            run('@0 wait row 5 contains "nunca" 150\n', fake=fake)
        self.assertIn("150 ms", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
