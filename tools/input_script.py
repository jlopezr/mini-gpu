"""Guiones de entrada para INPUT: teclado y ratón sin anfitrión interactivo.

Un guion es texto, una acción por línea, con el instante en el que ocurre:

    # comentario
    @0    keyboard connect            # @N: tras N instrucciones ejecutadas
    +100  key press H                 # +N: N instrucciones después de la línea anterior
    +10   type "hola\\n"               # teclado US; las mayúsculas llevan LSHIFT
    +50   key down LSHIFT A           # varias teclas = un solo report
    +50   key up LSHIFT A
    +20   mouse connect
    +20   mouse move 12 -5
    +20   mouse button left click
    +20   mouse report 0b101 4 4      # botones (bitmap) y movimiento en un report

Las acciones son las de `InputDevice` (teclado: `connect [teclas]`, `disconnect`,
`down`, `up`, `press`; ratón: `connect`, `disconnect`, `move`, `button`,
`report`) más `type`. Las teclas son nombres de `tools/hid_keys.py` o Usage IDs.

El «instante» es el de las instrucciones que el simulador completa (de CPU, o de
warp en las GPU). `@0` se aplica al cargar el guion, antes de la primera
instrucción. El guion se comprueba entero al cargarlo: una tecla sobre un
teclado sin conectar, por ejemplo, falla con el número de línea y no a media
simulación.
"""
from __future__ import annotations

import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tools import hid_keys
from tools.sim_devices import InputDevice

BUTTON_NAMES = {"LEFT": 0, "RIGHT": 1, "MIDDLE": 2}


@dataclass
class Action:
    at: int
    line: int
    run: Callable[[InputDevice], None]
    text: str


def _usages(names) -> list[int]:
    return [hid_keys.usage_of(name) for name in names]


def _pressed(device: InputDevice) -> set[int]:
    return set(device._bits(device.keys))


def _int(token: str, what: str) -> int:
    try:
        return int(token, 0)
    except ValueError:
        raise ValueError(f"{what} no es un entero: {token!r}") from None


def _button(token: str) -> int:
    name = token.upper()
    if name in BUTTON_NAMES:
        return BUTTON_NAMES[name]
    number = _int(token, "botón")
    if not 0 <= number < InputDevice.MOUSE_BUTTON_COUNT:
        raise ValueError(f"botón fuera de rango (0..31): {token!r}")
    return number


def _unescape(text: str) -> str:
    return (text.replace("\\n", "\n").replace("\\t", "\t")
            .replace('\\"', '"').replace("\\\\", "\\"))


def _compile(tokens: list[str]) -> list[Callable[[InputDevice], None]]:
    """Las llamadas que implementa una línea (puede ser más de una)."""
    device = tokens[0].lower()
    verb = tokens[1].lower() if len(tokens) > 1 else ""
    args = tokens[2:]

    if device == "type":
        text = _unescape(tokens[1])
        calls = []
        for stroke in hid_keys.keystrokes(text):
            usages = _usages(stroke)
            calls.append(lambda d, u=usages: d.keyboard_report(_pressed(d) | set(u)))
            calls.append(lambda d, u=usages: d.keyboard_report(_pressed(d) - set(u)))
        return calls

    if device == "keyboard":
        if verb == "connect":
            usages = _usages(args)
            return [lambda d: d.connect_keyboard(usages)]
        if verb == "disconnect" and not args:
            return [lambda d: d.disconnect_keyboard()]
        raise ValueError("keyboard admite `connect [teclas]` y `disconnect`")

    if device == "key":
        if verb not in ("down", "up", "press") or not args:
            raise ValueError("key admite `down|up|press TECLA...`")
        usages = set(_usages(args))
        down = lambda d: d.keyboard_report(_pressed(d) | usages)
        up = lambda d: d.keyboard_report(_pressed(d) - usages)
        return {"down": [down], "up": [up], "press": [down, up]}[verb]

    if device == "mouse":
        if verb == "connect":
            buttons = 0
            for token in args:
                buttons |= 1 << _button(token)
            return [lambda d: d.connect_mouse(buttons)]
        if verb == "disconnect" and not args:
            return [lambda d: d.disconnect_mouse()]
        if verb == "move" and len(args) == 2:
            dx, dy = _int(args[0], "dx"), _int(args[1], "dy")
            return [lambda d: d.mouse_move(dx, dy)]
        if verb == "button" and len(args) == 2:
            number = _button(args[0])
            action = args[1].lower()
            if action == "down":
                return [lambda d: d.mouse_button(number, True)]
            if action == "up":
                return [lambda d: d.mouse_button(number, False)]
            if action == "click":
                return [lambda d: d.mouse_button(number, True),
                        lambda d: d.mouse_button(number, False)]
            raise ValueError("mouse button admite `down`, `up` o `click`")
        if verb == "report" and len(args) == 3:
            buttons = _int(args[0], "botones")
            dx, dy = _int(args[1], "dx"), _int(args[2], "dy")
            return [lambda d: d.mouse_report(buttons, dx, dy)]
        raise ValueError("mouse admite `connect [botones]`, `disconnect`, "
                         "`move DX DY`, `button N down|up|click` y `report BOTONES DX DY`")

    raise ValueError(f"acción desconocida: {tokens[0]!r}")


def parse(text: str) -> list[Action]:
    """Interpreta un guion; devuelve las acciones ordenadas por instante."""
    actions: list[Action] = []
    now = 0
    for number, line in enumerate(text.splitlines(), 1):
        try:
            body = line.strip()
            if not body or body.startswith("#"):
                continue
            head, _, rest = body.partition(" ")
            if head[0] not in "@+" or not head[1:].isdigit():
                raise ValueError("la línea empieza por @N o +N")
            at = int(head[1:]) if head[0] == "@" else now + int(head[1:])
            if at < now:
                raise ValueError(f"el instante @{at} es anterior al de la línea previa ({now})")
            now = at
            rest = rest.strip()
            if not rest:
                raise ValueError("falta la acción")
            if rest.split(None, 1)[0] == "type":
                # `type` conserva el texto tal cual: puede llevar # o espacios.
                text = rest[4:].strip()
                if len(text) >= 2 and text[0] == text[-1] == '"':
                    text = text[1:-1]
                tokens = ["type", text]
            else:
                tokens = shlex.split(rest.split("#", 1)[0])
            for call in _compile(tokens):
                actions.append(Action(at, number, call, rest))
        except ValueError as error:
            raise ValueError(f"guion de entrada, línea {number}: {error}") from None
    return actions


def check(actions: list[Action], keyboard: bool = False, mouse: bool = False) -> None:
    """Ejecuta el guion entero sobre un dispositivo de prueba para detectar
    errores (una tecla sin teclado conectado...) antes de empezar a simular."""
    probe = InputDevice()
    if keyboard:
        probe.connect_keyboard()
    if mouse:
        probe.connect_mouse()
    for action in actions:
        try:
            action.run(probe)
        except ValueError as error:
            raise ValueError(
                f"guion de entrada, línea {action.line} ({action.text}): {error}") from None


class _Recorder(InputDevice):
    """El oráculo de INPUT, sin límite de FIFO: guarda los eventos que saldrían.

    Sirve para pasar un guion a la placa. El dispositivo real tiene su propia
    FIFO de 16 palabras; aquí lo único que interesa es QUÉ eventos produce cada
    acción y en qué orden, así que se recogen todos y es `play_on_board` quien
    decide cuándo cabe mandarlos.
    """

    def __init__(self):
        super().__init__()
        self.emitted: list[int] = []

    def _push(self, word: int) -> None:
        self.emitted.append(word)


def play_on_board(client, actions: list[Action], timeout: float = 10.0,
                  clock: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep) -> None:
    """Reproduce un guion sobre el INPUT de la placa, por el monitor.

    El guion está escrito en instrucciones (`@N`), y la placa no cuenta
    instrucciones desde el host: el instante se IGNORA y solo se conserva el
    ORDEN. Vale para los casos cuyo programa espera cada evento sondeando
    `STATUS.COUNT`, que es lo que hacen los de `extensions/input`: lo que
    observan es qué llega y en qué orden, no cuándo.

    Cada acción se ejecuta sobre un dispositivo sombra, que produce los eventos
    exactos del oráculo (mismo orden, mismas reglas de conexión y desconexión), y
    esos eventos se mandan con `INPUT_EVENTS` respetando los huecos libres que
    devuelve cada respuesta. La presencia se pone ANTES de los eventos cuando se
    conecta algo y DESPUÉS cuando se desconecta, como en §25.11.

    Exige la FIFO de la placa vacía al empezar: solo la CPU puede vaciarla, así
    que un evento sin consumir de otra sesión contaminaría el caso, y es mejor
    avisar que dar un resultado raro.
    """
    deadline = clock() + timeout
    depth = client.INPUT_FIFO_DEPTH
    free = client.set_input_presence(False, False)
    if free != depth:
        raise RuntimeError(
            f"la FIFO de INPUT tiene {depth - free} evento(s) sin consumir de una "
            "sesión anterior; reinicia la placa o deja que un programa los lea")
    shadow = _Recorder()
    sent = (False, False)

    def wait_room() -> int:
        nonlocal free
        while free == 0:
            if clock() >= deadline:
                raise TimeoutError(
                    "la CPU no vació la FIFO de INPUT: el guion no cabe")
            sleep(0.005)
            free = client.send_input_events([])
        return free

    for action in actions:
        try:
            action.run(shadow)
        except ValueError as error:
            raise ValueError(
                f"guion de entrada, línea {action.line} ({action.text}): {error}"
            ) from None
        words, shadow.emitted = shadow.emitted, []
        presence = (shadow.keyboard_present, shadow.mouse_present)
        connecting = any(now and not before for now, before in zip(presence, sent))
        if connecting:
            free = client.set_input_presence(*presence)
            sent = presence
        while words:
            take = min(wait_room(), len(words))
            free = client.send_input_events(words[:take])
            words = words[take:]
        if presence != sent:
            free = client.set_input_presence(*presence)
            sent = presence


def load(path: Path, keyboard: bool = False, mouse: bool = False) -> list[Action]:
    actions = parse(Path(path).read_text(encoding="utf-8"))
    check(actions, keyboard, mouse)
    return actions
