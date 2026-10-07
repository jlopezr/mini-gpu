"""Reproducir un guion de INPUT sobre la placa, sin placa.

`tools.input_script.play_on_board` ejecuta el guion sobre un dispositivo sombra y
manda sus eventos por el monitor. El cliente falso es la FPGA: aplica cada
palabra con `InputDevice.apply_event` y contesta los huecos libres, y el "sleep"
inyectado es la CPU sacando eventos de la FIFO.

Se comprueba que a la placa llega EXACTAMENTE lo que el oraculo produce para el
mismo guion, en el mismo orden, y que la presencia se pone antes de los eventos
al conectar y despues al desconectar.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import input_script  # noqa: E402
from tools.sim_devices import InputDevice as D  # noqa: E402

KEYS_AND_MOUSE = """\
@0   keyboard connect
@0   mouse connect
@200 key down LSHIFT A
@400 key up LSHIFT A
@600 mouse report 1 3 -2
@800 mouse report 0 0 0
"""


class FakeBoard:
    INPUT_FIFO_DEPTH = D.FIFO_DEPTH

    def __init__(self):
        self.device = D()
        self.commands = []          # ("events", [...]) o ("presence", kbd, mouse)
        self.received = []

    def _free(self):
        return D.FIFO_DEPTH - len(self.device.fifo)

    def send_input_events(self, words):
        words = list(words)
        self.commands.append(("events", words))
        for word in words:
            self.device.apply_event(word)
            self.received.append(word)
        return self._free()

    def set_input_presence(self, keyboard, mouse):
        self.commands.append(("presence", keyboard, mouse))
        self.device.set_presence(keyboard, mouse)
        return self._free()

    def cpu_read(self, n=1):
        for _ in range(n):
            if self.device.fifo:
                self.device.read(D.EVENT_DATA)


def oracle_words(text):
    """Los eventos que el simulador produciria para el guion, sin limite de FIFO."""
    class Recorder(D):
        def __init__(self):
            super().__init__()
            self.out = []

        def _push(self, word):
            self.out.append(word)

    device = Recorder()
    for action in input_script.parse(text):
        action.run(device)
    return device.out


class PlayOnBoardTest(unittest.TestCase):
    def test_llega_lo_mismo_que_produce_el_oraculo(self):
        board = FakeBoard()
        input_script.play_on_board(board, input_script.parse(KEYS_AND_MOUSE))
        self.assertEqual(oracle_words(KEYS_AND_MOUSE), board.received)
        # Los siete eventos del programa de prueba.
        self.assertEqual(7, len(board.received))

    def test_presencia_antes_al_conectar_y_estado_final(self):
        board = FakeBoard()
        input_script.play_on_board(board, input_script.parse(KEYS_AND_MOUSE))
        presencias = [c for c in board.commands if c[0] == "presence"]
        # Primero a cero (estado limpio), luego cada dispositivo al conectarse.
        self.assertEqual(("presence", False, False), presencias[0])
        self.assertEqual(("presence", True, False), presencias[1])
        self.assertEqual(("presence", True, True), presencias[2])
        self.assertTrue(board.device.keyboard_present)
        self.assertTrue(board.device.mouse_present)
        # La presencia llega antes de los eventos que dependen de ella.
        primer_evento = next(i for i, c in enumerate(board.commands)
                             if c[0] == "events" and c[1])
        self.assertLess(board.commands.index(("presence", True, True)),
                        primer_evento)

    def test_desconectar_manda_los_eventos_antes_que_la_presencia(self):
        texto = "@0 keyboard connect A\n@1 keyboard disconnect\n"
        board = FakeBoard()
        input_script.play_on_board(board, input_script.parse(texto))
        ultimo = board.commands[-1]
        self.assertEqual(("presence", False, False), ultimo)
        liberacion = [i for i, c in enumerate(board.commands)
                      if c[0] == "events" and c[1]]
        self.assertTrue(liberacion)
        self.assertLess(liberacion[-1], len(board.commands) - 1)
        self.assertEqual(oracle_words(texto), board.received)

    def test_un_guion_mas_largo_que_la_fifo_espera_a_la_cpu(self):
        texto = "@0 keyboard connect\n" + "".join(
            f"+1 key press {tecla}\n" for tecla in "ABCDEFGHIJ" * 4)
        board = FakeBoard()
        input_script.play_on_board(
            board, input_script.parse(texto),
            sleep=lambda _: board.cpu_read(4))
        self.assertEqual(oracle_words(texto), board.received)
        self.assertGreater(len(board.received), D.FIFO_DEPTH)
        self.assertFalse(board.device.overflow)

    def test_si_la_cpu_no_vacia_la_fifo_falla_con_timeout(self):
        texto = "@0 keyboard connect\n" + "".join(
            f"+1 key press {tecla}\n" for tecla in "ABCDEFGHIJ" * 4)
        board = FakeBoard()
        reloj = iter(range(0, 10_000))
        with self.assertRaises(TimeoutError):
            input_script.play_on_board(
                board, input_script.parse(texto), timeout=5,
                clock=lambda: next(reloj), sleep=lambda _: None)

    def test_fifo_con_eventos_de_otra_sesion_se_rechaza(self):
        board = FakeBoard()
        board.device.apply_event(D.key_event(0x04, True, 0))
        with self.assertRaises(RuntimeError) as error:
            input_script.play_on_board(board, input_script.parse(KEYS_AND_MOUSE))
        self.assertIn("sin consumir", str(error.exception))

    def test_un_error_del_guion_dice_la_linea(self):
        board = FakeBoard()
        with self.assertRaises(ValueError) as error:
            input_script.play_on_board(
                board, input_script.parse("@0 key down A\n"))
        self.assertIn("línea 1", str(error.exception))


if __name__ == "__main__":
    unittest.main()
