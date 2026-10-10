"""`tools/board_input.py`, sin placa.

El cliente falso hace de FPGA (aplica cada palabra con `InputDevice.apply_event`,
como `input_registers.v`) y de aplicación de la placa: lleva un puntero relativo
que recorta a 640x480, como `console_mini.c`, y tiene una pantalla de texto que
se lee palabra a palabra. Se comprueba lo que un programa de prueba quiere dar
por hecho: que un clic en (columna, fila) cae en esa celda, estando el puntero
donde estuviera, y que las teclas y la pantalla salen como se esperan.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "x.tests"))

from unit.input.test_input_adapter import FakeClient  # noqa: E402

from tools import board_input  # noqa: E402
from tools.board_input import BoardInput, read_screen  # noqa: E402
from tools.sim_devices import InputDevice as D  # noqa: E402


class FakeBoard(FakeClient):
    """La FPGA con una aplicación: puntero recortado, pantalla de texto y CPU."""

    def __init__(self, pointer=(500, 100)):
        super().__init__()
        self.pointer = list(pointer)    # donde lo dejó una sesión anterior
        self.clicks = []                # (celda, boton) en cada pulsación
        self.keys_down = []
        self.keys_up = []               # lo que la aplicacion ve soltarse
        self.buttons_up = []
        self.text = {}                  # (columna, fila) -> carácter

    def send_input_events(self, words):
        free = super().send_input_events(words)
        # La "CPU" de la aplicación saca los eventos al instante.
        while self.device.fifo:
            event = D.decode_event(self.device.read(D.EVENT_DATA))
            if event["type"] == "move":
                self.pointer[0] = max(0, min(639, self.pointer[0] + event["dx"]))
                self.pointer[1] = max(0, min(479, self.pointer[1] + event["dy"]))
            elif event["type"] == "button" and event["down"]:
                self.clicks.append(((self.pointer[0] // 8, self.pointer[1] // 16),
                                    event["button"]))
            elif event["type"] == "key" and event["down"]:
                self.keys_down.append(event["usage"])
            elif event["type"] == "key" and event["usage"]:
                self.keys_up.append(event["usage"])
            elif event["type"] == "button" and not event["down"]:
                self.buttons_up.append(event["button"])
        return D.FIFO_DEPTH if len(words) else free

    def read_word(self, address):
        index = (address - board_input.TEXT_BASE) // 4
        row, column = divmod(index, board_input.COLS)
        return ord(self.text.get((column, row), " "))


def board(**kwargs):
    fake = FakeBoard(**kwargs)
    return fake, BoardInput(fake, settle=0)


class ClickTest(unittest.TestCase):
    def test_el_clic_cae_en_la_celda_pedida_desde_cualquier_puntero(self):
        for start in [(320, 240), (0, 0), (639, 479), (500, 100)]:
            fake, session = board(pointer=start)
            with session as b:
                b.click(53, 6)
                b.click(0, 0)
                b.click(79, 29, button=1)
            self.assertEqual(fake.clicks, [((53, 6), 0), ((0, 0), 0), ((79, 29), 1)],
                             start)

    def test_sin_home_no_se_sabe_donde_cae(self):
        fake = FakeBoard(pointer=(500, 100))
        with BoardInput(fake, home=False, settle=0) as b:
            b.click(40, 15)
        self.assertNotEqual(fake.clicks[0][0], (40, 15))


class KeyTest(unittest.TestCase):
    def test_tap_pulsa_y_suelta_por_nombre_o_por_usage(self):
        fake, session = board()
        with session as b:
            b.tap("A")
            b.tap(0x05)
        self.assertEqual(fake.keys_down, [0x04, 0x05])
        self.assertEqual(fake.device.keys, 0)

    def test_varias_teclas_a_la_vez_y_se_sueltan_al_salir(self):
        fake, session = board()
        with session as b:
            b.key_down("LSHIFT", "A")
            self.assertTrue(fake.device.keys)
        self.assertEqual(fake.device.keys, 0)
        self.assertFalse(fake.device.keyboard_present)


class ScreenTest(unittest.TestCase):
    def test_lee_filas_y_busca_texto(self):
        fake, session = board()
        for i, ch in enumerate("hola"):
            fake.text[(10 + i, 13)] = ch
        for i, ch in enumerate("Control: Edit"):
            fake.text[(60 + i, 29)] = ch
        with session as b:
            shot = b.screen(rows=[13, 29])
            self.assertEqual(shot.row(13), "          hola")
            self.assertEqual(shot.find("hola"), (10, 13))
            self.assertIn("Control: Edit", shot)
            self.assertNotIn("adios", shot)
            self.assertEqual(sorted(shot.cells), [13, 29])
            self.assertEqual(b.wait_for("hola", timeout=0.2, rows=[13]).find("hola"),
                             (10, 13))
            with self.assertRaises(TimeoutError):
                b.wait_for("adios", timeout=0.05, rows=[13])

    def test_los_codigos_bajos_son_dibujos_y_no_caracteres_de_control(self):
        # Los triangulos de las barras y del combo son 0x1E y 0x1F.
        self.assertEqual(board_input.glyph(0x1E), "▲")
        self.assertEqual(board_input.glyph(0x1F), "▼")
        self.assertEqual(board_input.glyph(0x10), "►")
        self.assertEqual(board_input.glyph(0x41), "A")
        self.assertEqual(board_input.glyph(0xA4), "ñ")
        self.assertEqual(board_input.glyph(0xFB), "√")
        self.assertEqual(board_input.glyph(127), "⌂")
        fake, session = board()
        fake.text[(3, 7)] = chr(0x1F)
        with session as b:
            self.assertEqual(b.screen(rows=[7]).row(7), "   ▼")
            self.assertEqual(b.screen(rows=[7]).find("▼"), (3, 7))

    def test_la_pantalla_entera_son_treinta_filas_de_ochenta(self):
        fake, session = board()
        shot = read_screen(fake)
        self.assertEqual(len(shot.rows), board_input.ROWS)
        self.assertEqual(shot.rows, [""] * board_input.ROWS)


if __name__ == "__main__":
    unittest.main()
