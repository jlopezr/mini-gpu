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


def load(path: Path, keyboard: bool = False, mouse: bool = False) -> list[Action]:
    actions = parse(Path(path).read_text(encoding="utf-8"))
    check(actions, keyboard, mouse)
    return actions
