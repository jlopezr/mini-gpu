"""Teclado, ratón y pantalla de la placa desde Python, para pruebas automáticas.

`monitor.py input` es para una persona con la ventana delante. Esto es lo mismo
sin ventana: un programa de prueba pulsa teclas, mueve y hace clic con el ratón
y lee lo que ha quedado en la pantalla de texto, y decide si está bien.

    with BoardInput(client) as board:
        board.tap("H", "O", "L", "A")
        board.click(53, 6)                      # columna, fila de la pantalla de texto
        assert "Control: Edit" in board.screen().row(29)
        board.wait_for("hola")

Lo que da de más sobre llamar a `InputAdapter` directamente:

  - El puntero de la placa se resincroniza al empezar (`InputAdapter.home`), y
    se lleva la cuenta de dónde está, así que `click(col, fila)` cae en esa celda
    sea cual sea el estado en el que dejó la placa una sesión anterior.
  - Cada acción espera a que la CPU de la placa haya sacado los eventos de la
    FIFO y deja un momento para que la aplicación repinte.
  - Se puede leer la pantalla de texto como filas de texto, sin ventana. La RAM de
    texto solo se puede leer palabra a palabra por el monitor (el bloque no vale
    para MMIO): ~2 ms cada una, unos 5 s la pantalla entera. `rows=` lee solo las
    filas que hacen falta.

No sabe de Tk ni abre ventanas. Como el adaptador, habla con cualquier cliente que
tenga `send_input_events`, `set_input_presence` y `read_word`, de modo que se
prueba sin placa. Los guiones de `tools/board_script.py` lo usan por debajo.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import hid_keys  # noqa: E402
from tools.input_adapter import InputAdapter  # noqa: E402
from tools.sim_devices import InputDevice  # noqa: E402

# La pantalla de texto de la 30 (mmio.md): 80x30 celdas de 8x16 puntos.
TEXT_BASE = 0x8020_6000
COLS, ROWS = 80, 30
CELL_W, CELL_H = 8, 16
SCREEN_W, SCREEN_H = COLS * CELL_W, ROWS * CELL_H


class Screen:
    """Una foto de la pantalla de texto: una palabra por celda (mmio.md §9)."""

    def __init__(self, cells: dict[int, list[int]]):
        self.cells = cells                  # fila -> COLS palabras

    def row(self, number: int) -> str:
        """El texto de una fila, sin los espacios del final (CP437)."""
        words = self.cells[number]
        return "".join(bytes([w & 0xFF]).decode("cp437") for w in words).rstrip()

    @property
    def rows(self) -> list[str]:
        return [self.row(r) for r in sorted(self.cells)]

    @property
    def text(self) -> str:
        return "\n".join(self.rows)

    def find(self, text: str) -> tuple[int, int] | None:
        """(columna, fila) de la primera aparición de `text`, o None."""
        for number in sorted(self.cells):
            column = self.row(number).find(text)
            if column >= 0:
                return column, number
        return None

    def __contains__(self, text: str) -> bool:
        return self.find(text) is not None

    def cell(self, column: int, row: int) -> int:
        """La palabra de la celda: carácter en el byte bajo, colores arriba."""
        return self.cells[row][column]


def read_screen(client, rows=None) -> Screen:
    """Lee la pantalla de texto (o solo las `rows` pedidas) por el monitor."""
    wanted = range(ROWS) if rows is None else rows
    cells = {}
    for number in wanted:
        base = TEXT_BASE + number * COLS * 4
        cells[number] = [client.read_word(base + 4 * column) for column in range(COLS)]
    return Screen(cells)


def _usage(key) -> int:
    return key if isinstance(key, int) else hid_keys.usage_of(key)


class BoardInput:
    """Un teclado y un ratón del PC conectados a la placa, para un programa.

    Con `connect=False` empieza sin presencia (como un dispositivo sin conectar)
    y quien lo usa llama a `set_presence` y `send_words`: así trabajan los guiones.
    """

    def __init__(self, client, home: bool = True, settle: float = 0.15,
                 connect: bool = True):
        self.client = client
        self.adapter = InputAdapter(client)
        self.home = home
        self.connect = connect
        self.settle = settle                # lo que se deja a la aplicación para repintar
        self.px = SCREEN_W // 2             # dónde está el puntero de la placa
        self.py = SCREEN_H // 2
        self.pressed: set[int] = set()
        self.buttons = 0
        self.mouse_present = connect

    # ---- ciclo de vida --------------------------------------------------------

    def __enter__(self) -> "BoardInput":
        if self.connect:
            self.adapter.connect()
            self.px, self.py = SCREEN_W // 2, SCREEN_H // 2
            if self.home:
                self.adapter.home(self.px, self.py)
        else:
            # Sin teclado ni ratón hasta que alguien los conecte (un guion).
            self.adapter.free = self.client.set_input_presence(False, False)
            self.adapter.connected = True
        self.flush(settle=False)
        return self

    def __exit__(self, *exc) -> None:
        if self.connect:
            self.adapter.close()
        else:
            self.flush(settle=False)
            self.adapter.free = self.client.set_input_presence(False, False)
            self.adapter.connected = False

    def flush(self, timeout: float = 5.0, settle: bool = True) -> bool:
        """Espera a que todo haya salido y la CPU de la placa lo haya consumido.

        Con `settle`, deja además un momento a la aplicación para repintar."""
        deadline = time.monotonic() + timeout
        while self.adapter.pending and time.monotonic() < deadline:
            if not self.adapter.pump():
                time.sleep(0.001)
        while time.monotonic() < deadline:
            self.adapter.free = self.client.send_input_events([])
            if self.adapter.free == InputDevice.FIFO_DEPTH:
                if settle:
                    time.sleep(self.settle)
                return True
        return False

    # ---- palabras ya formadas (los guiones) -------------------------------------

    def set_presence(self, keyboard: bool, mouse: bool) -> None:
        """Conecta o desconecta. Lo pendiente sale antes; al conectar el ratón, el
        puntero se resincroniza igual que al empezar."""
        arrives = mouse and not self.mouse_present
        self.flush(settle=False)
        self.adapter.free = self.client.set_input_presence(keyboard, mouse)
        self.mouse_present = mouse
        if arrives and self.home:
            self.px, self.py = SCREEN_W // 2, SCREEN_H // 2
            self.adapter.home(self.px, self.py)
            self.flush(settle=False)

    def send_words(self, words) -> None:
        """Manda palabras de evento ya formadas, llevando la cuenta del puntero."""
        for word in words:
            event = InputDevice.decode_event(word)
            if event["type"] == "move":
                self.px = max(0, min(SCREEN_W - 1, self.px + event["dx"]))
                self.py = max(0, min(SCREEN_H - 1, self.py + event["dy"]))
        self.adapter.queue += list(words)
        self.flush(settle=False)

    # ---- teclado --------------------------------------------------------------

    def _keys(self) -> None:
        self.adapter.keys_report(sorted(self.pressed))

    def key_down(self, *keys) -> None:
        self.pressed.update(_usage(k) for k in keys)
        self._keys()
        self.flush()

    def key_up(self, *keys) -> None:
        self.pressed.difference_update(_usage(k) for k in keys)
        self._keys()
        self.flush()

    def tap(self, *keys) -> None:
        """Pulsa y suelta. Varias teclas se pulsan a la vez (Shift+A)."""
        self.key_down(*keys)
        self.key_up(*keys)

    # ---- ratón ----------------------------------------------------------------

    def _report(self, dx: int = 0, dy: int = 0) -> None:
        # Lo que la aplicación recorta a la pantalla, la cuenta también.
        self.px = max(0, min(SCREEN_W - 1, self.px + dx))
        self.py = max(0, min(SCREEN_H - 1, self.py + dy))
        self.adapter.mouse_report(self.buttons, dx, dy)

    @staticmethod
    def cell_center(column: int, row: int) -> tuple[int, int]:
        """El punto (x, y) del centro de una celda de la pantalla de texto."""
        return column * CELL_W + CELL_W // 2, row * CELL_H + CELL_H // 2

    def move_to_cell(self, column: int, row: int) -> None:
        """Lleva el puntero al centro de una celda de la pantalla de texto."""
        target_x, target_y = self.cell_center(column, row)
        self._report(target_x - self.px, target_y - self.py)
        self.flush()

    def click(self, column: int, row: int, button: int = 0) -> None:
        self.move_to_cell(column, row)
        self.buttons |= 1 << button
        self._report()
        self.flush()
        self.buttons &= ~(1 << button)
        self._report()
        self.flush()

    # ---- pantalla -------------------------------------------------------------

    def screen(self, rows=None) -> Screen:
        return read_screen(self.client, rows)

    def wait_for(self, text: str, timeout: float = 5.0, rows=None) -> Screen:
        """Lee la pantalla hasta que aparezca `text`. TimeoutError si no."""
        deadline = time.monotonic() + timeout
        while True:
            shot = self.screen(rows)
            if text in shot:
                return shot
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{text!r} no aparece en la pantalla:\n{shot.text}")
