"""Guiones de entrada para la placa: `monitor.py input --script guion.txt`.

Es el mismo formato que `tools/input_script.py` (el del simulador), con dos
cambios: el instante `@N` / `+N` está en **milisegundos** (en el simulador son
instrucciones), y hay verbos que solo tienen sentido con una placa delante, que
mira la pantalla y puede equivocarse:

    @0     keyboard connect
    +0     mouse connect
    +300   type "hola"                    # teclado US, como en el simulador
    +100   key press LSHIFT SEMICOLON
    +100   click 53 6                     # columna, fila de la pantalla de texto
    +100   click 53 6 right               # con otro botón
    +100   moveto 40 15                   # solo mueve el puntero a esa celda
    +200   expect row 13 contains "hola"
    +0     expect row 29 is "Control: Edit"
    +0     expect screen absent "Error"
    +0     wait row 29 contains "Edit" 3000   # espera hasta 3000 ms (5000 por defecto)

Las acciones de teclado y ratón (`keyboard`, `key`, `mouse`, `type`) son las de
`InputDevice` y se ejecutan sobre un dispositivo de sombra que genera los mismos
eventos que el simulador; aquí se mandan a la placa en vez de a un dispositivo
simulado. `click` y `moveto` cuentan con que el puntero de la placa está donde cree
la sombra: al conectar el ratón se resincroniza (`InputAdapter.home`).

`expect` mira la pantalla de texto después de dejar a la aplicación el tiempo de
repintar (`settle`). `row N` lee solo esa fila (~0,2 s); `screen`, las 30 (~5 s).
Una comprobación que falla para el guion y dice qué esperaba y qué vio.
"""
from __future__ import annotations

import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import board_input, input_script  # noqa: E402
from tools.sim_devices import InputDevice  # noqa: E402

DEFAULT_WAIT_MS = 5000
POLL_SECONDS = 0.1


class ScriptError(ValueError):
    """El guion está mal escrito (se detecta al cargarlo, antes de tocar la placa)."""


class ScriptFailure(Exception):
    """Una comprobación falló o la placa no hizo lo esperado, ejecutando el guion."""


class ShadowDevice(InputDevice):
    """El dispositivo de INPUT de la placa, tal como el guion cree que está.

    Las acciones del guion corren sobre él y sus eventos salen hacia la placa; la
    FIFO de verdad la tiene la FPGA, así que la de aquí no se llena nunca."""

    FIFO_DEPTH = 1 << 20


@dataclass
class Step:
    at: int                                 # ms desde el principio
    line: int
    text: str
    run: Callable[["Runner"], None]
    device: Callable[[InputDevice], None] | None = None     # para la comprobación previa
    needs_mouse: bool = False


# ---- interpretación ---------------------------------------------------------------


def _int(token: str, what: str) -> int:
    try:
        return int(token, 0)
    except ValueError:
        raise ScriptError(f"{what} no es un entero: {token!r}") from None


def _cell(column: str, row: str) -> tuple[int, int]:
    col, line = _int(column, "columna"), _int(row, "fila")
    if not 0 <= col < board_input.COLS or not 0 <= line < board_input.ROWS:
        raise ScriptError(f"la celda ({col}, {line}) está fuera de la pantalla "
                          f"({board_input.COLS}x{board_input.ROWS})")
    return col, line


def _button(token: str) -> int:
    name = token.upper()
    if name in input_script.BUTTON_NAMES:
        return input_script.BUTTON_NAMES[name]
    return _int(token, "botón")


def _scope(tokens: list[str]) -> tuple[list[int] | None, list[str]]:
    """`row N` o `screen`: las filas a leer (None = todas) y lo que sobra."""
    if tokens and tokens[0].lower() == "screen":
        return None, tokens[1:]
    if len(tokens) >= 2 and tokens[0].lower() == "row":
        row = _int(tokens[1], "fila")
        if not 0 <= row < board_input.ROWS:
            raise ScriptError(f"la fila {row} no existe (0..{board_input.ROWS - 1})")
        return [row], tokens[2:]
    raise ScriptError("se espera `row N` o `screen`")


def _condition(rows, tokens: list[str]):
    """(operador, texto, resto) de `contains|is|absent "texto"`."""
    if len(tokens) < 2 or tokens[0].lower() not in ("contains", "is", "absent"):
        raise ScriptError("se espera `contains`, `is` o `absent` y un texto")
    operator = tokens[0].lower()
    if operator == "is" and (rows is None or len(rows) != 1):
        raise ScriptError("`is` compara una fila entera: `row N is \"texto\"`")
    return operator, tokens[1], tokens[2:]


def _holds(shot: board_input.Screen, rows, operator: str, text: str) -> bool:
    if operator == "is":
        return shot.row(rows[0]) == text
    present = text in shot
    return present if operator == "contains" else not present


def _describe(rows, operator: str, text: str) -> str:
    where = "la pantalla" if rows is None else f"la fila {rows[0]}"
    verb = {"contains": "contenga", "is": "sea", "absent": "no contenga"}[operator]
    return f"{where} {verb} {text!r}"


def _board_step(at: int, line: int, rest: str, tokens: list[str]) -> Step:
    verb = tokens[0].lower()
    args = tokens[1:]

    if verb in ("click", "moveto"):
        if verb == "click" and len(args) not in (2, 3):
            raise ScriptError("click admite `COLUMNA FILA [BOTON]`")
        if verb == "moveto" and len(args) != 2:
            raise ScriptError("moveto admite `COLUMNA FILA`")
        column, row = _cell(args[0], args[1])
        button = _button(args[2]) if len(args) == 3 else 0
        if verb == "click":
            return Step(at, line, rest, lambda r: r.click(column, row, button),
                        needs_mouse=True)
        return Step(at, line, rest, lambda r: r.moveto(column, row), needs_mouse=True)

    rows, args = _scope(args)
    operator, text, args = _condition(rows, args)
    if verb == "expect":
        if args:
            raise ScriptError(f"sobra: {' '.join(args)}")
        return Step(at, line, rest, lambda r: r.expect(rows, operator, text))
    # wait
    if len(args) > 1:
        raise ScriptError(f"sobra: {' '.join(args[1:])}")
    timeout = _int(args[0], "tiempo") if args else DEFAULT_WAIT_MS
    return Step(at, line, rest, lambda r: r.wait(rows, operator, text, timeout))


def parse(text: str) -> list[Step]:
    """Interpreta un guion; devuelve los pasos ordenados por instante."""
    steps: list[Step] = []
    now = 0
    for number, line in enumerate(text.splitlines(), 1):
        try:
            body = line.strip()
            if not body or body.startswith("#"):
                continue
            head, _, rest = body.partition(" ")
            if head[0] not in "@+" or not head[1:].isdigit():
                raise ScriptError("la línea empieza por @N o +N (milisegundos)")
            at = int(head[1:]) if head[0] == "@" else now + int(head[1:])
            if at < now:
                raise ScriptError(f"el instante @{at} es anterior al de la línea previa ({now})")
            now = at
            rest = rest.strip()
            if not rest:
                raise ScriptError("falta la acción")
            verb = rest.split(None, 1)[0].lower()
            if verb in ("click", "moveto", "expect", "wait"):
                try:
                    tokens = shlex.split(rest, comments=True)
                except ValueError as error:
                    raise ScriptError(str(error)) from None
                steps.append(_board_step(at, number, rest, tokens))
                continue
            # Una acción de teclado o ratón: la entiende el intérprete del simulador.
            try:
                actions = input_script.parse(f"@0 {rest}")
            except ValueError as error:
                raise ScriptError(str(error).split(": ", 1)[-1]) from None
            for action in actions:
                steps.append(Step(at, number, rest,
                                  lambda r, call=action.run: r.device(call),
                                  device=action.run))
        except ScriptError as error:
            raise ScriptError(f"guion, línea {number}: {error}") from None
    return steps


def check(steps: list[Step]) -> None:
    """Ejecuta el guion sobre un dispositivo de prueba para detectar errores
    (una tecla sin teclado conectado...) antes de tocar la placa."""
    probe = ShadowDevice()
    for step in steps:
        try:
            if step.device is not None:
                step.device(probe)
            if step.needs_mouse and not probe.mouse_present:
                raise ValueError("ratón no presente")
        except ValueError as error:
            raise ScriptError(f"guion, línea {step.line} ({step.text}): {error}") from None


def load(path) -> list[Step]:
    steps = parse(Path(path).read_text(encoding="utf-8"))
    check(steps)
    return steps


# ---- ejecución --------------------------------------------------------------------


class Runner:
    def __init__(self, board: board_input.BoardInput, log: Callable[[str], None]):
        self.board = board
        self.log = log
        self.shadow = ShadowDevice()
        self.checks = 0

    def device(self, call: Callable[[InputDevice], None]) -> None:
        """Una acción de teclado o ratón: la sombra genera los eventos y salen."""
        shadow = self.shadow
        was_keyboard, was_mouse = shadow.keyboard_present, shadow.mouse_present
        call(shadow)
        words = list(shadow.fifo)
        shadow.fifo.clear()
        keyboard, mouse = shadow.keyboard_present, shadow.mouse_present
        if (keyboard and not was_keyboard) or (mouse and not was_mouse):
            self.board.set_presence(keyboard, mouse)      # primero la presencia...
        self.board.send_words(words)                      # ...los eventos...
        if (was_keyboard and not keyboard) or (was_mouse and not mouse):
            self.board.set_presence(keyboard, mouse)      # ...y al irse, al final

    def moveto(self, column: int, row: int) -> None:
        x, y = board_input.BoardInput.cell_center(column, row)
        self.device(lambda d: d.mouse_move(x - self.board.px, y - self.board.py))

    def click(self, column: int, row: int, button: int) -> None:
        self.moveto(column, row)
        self.device(lambda d: d.mouse_button(button, True))
        self.device(lambda d: d.mouse_button(button, False))

    def _look(self, rows) -> board_input.Screen:
        self.board.flush(settle=True)
        return board_input.read_screen(self.board.client, rows)

    def expect(self, rows, operator: str, text: str) -> None:
        shot = self._look(rows)
        self.checks += 1
        if not _holds(shot, rows, operator, text):
            seen = shot.row(rows[0]) if rows is not None else shot.text
            raise ScriptFailure(f"esperaba que {_describe(rows, operator, text)}, y hay:\n"
                                f"{seen}")

    def wait(self, rows, operator: str, text: str, timeout_ms: int) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        self.board.flush(settle=True)
        while True:
            shot = board_input.read_screen(self.board.client, rows)
            if _holds(shot, rows, operator, text):
                self.checks += 1
                return
            if time.monotonic() >= deadline:
                seen = shot.row(rows[0]) if rows is not None else shot.text
                raise ScriptFailure(
                    f"tras {timeout_ms} ms sigue sin cumplirse que "
                    f"{_describe(rows, operator, text)}; hay:\n{seen}")
            time.sleep(POLL_SECONDS)

    def release_everything(self) -> None:
        """Al terminar, aunque sea por un error: nada pulsado y sin presencia."""
        self.device(lambda d: d.disconnect_keyboard())
        self.device(lambda d: d.disconnect_mouse())


def run(client, steps: list[Step], home: bool = True, settle: float = 0.15,
        log: Callable[[str], None] = print) -> int:
    """Ejecuta el guion en la placa. Devuelve cuántas comprobaciones pasaron."""
    with board_input.BoardInput(client, home=home, settle=settle,
                                connect=False) as board:
        runner = Runner(board, log)
        start = time.monotonic()
        shown = None
        try:
            for step in steps:
                wait = start + step.at / 1000 - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                if step.line != shown:           # un `type` son muchos pasos
                    shown = step.line
                    log(f"[{time.monotonic() - start:6.2f} s] línea {step.line}: {step.text}")
                try:
                    step.run(runner)
                except ValueError as error:
                    raise ScriptFailure(f"línea {step.line} ({step.text}): {error}") from None
                except ScriptFailure as error:
                    raise ScriptFailure(f"línea {step.line} ({step.text}): {error}") from None
        finally:
            try:
                runner.release_everything()
            except (KeyboardInterrupt, ValueError):
                pass
    return runner.checks
