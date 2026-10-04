"""Del teclado y el ratón del anfitrión a reports de INPUT.

La ventana de un simulador (o del depurador) recibe eventos de Tk; INPUT
(`1.isa/mmio.md` §25) quiere **teclas físicas** como Usage IDs HID y reports
de estado completo. Este módulo hace esa traducción sin depender de Tk, para
poder probarla sin ventana: la ventana le pasa eventos y él devuelve reports.

Lo que se aprendió de Tk en Windows (sondeo con teclado español):

* Mantener una tecla manda `KeyPress` repetidos y ningún `KeyRelease` entre
  medias: se ignora el `KeyPress` de una tecla ya pulsada.
* `keycode` es el Virtual-Key. En las teclas OEM depende del layout (la `ñ`
  es `VK_OEM_3`), así que las teclas físicas salen de
  `MapVirtualKey(vk)` -> scancode -> HID, que no depende del layout.
* Shift izquierdo y derecho comparten `keycode`, el derecho se suelta con
  `keysym=Shift_L` y con los dos pulsados solo llega un release: los
  modificadores se leen con `GetAsyncKeyState`, no de los eventos.
* AltGr llega como `Control_L` + `Alt_R` con un milisegundo de diferencia: el
  `Control_L` es falso y se retira.
* La tecla Windows abre el menú Inicio y no entrega release: al perder el foco
  se suelta todo.
"""
from __future__ import annotations

import sys
from typing import Callable

from tools import hid_keys

# Scancode set 1 -> Usage ID HID. La clave es (extendido, scancode): el prefijo
# E0 distingue, p. ej., Enter de Enter del teclado numérico.
SCAN_TO_HID: dict[tuple[bool, int], int] = {}


def _scan(extended: bool, table: dict[int, str]) -> None:
    for scancode, name in table.items():
        SCAN_TO_HID[(extended, scancode)] = hid_keys.usage_of(name)


_scan(False, {
    0x01: "ESC", 0x02: "1", 0x03: "2", 0x04: "3", 0x05: "4", 0x06: "5",
    0x07: "6", 0x08: "7", 0x09: "8", 0x0A: "9", 0x0B: "0", 0x0C: "MINUS",
    0x0D: "EQUAL", 0x0E: "BACKSPACE", 0x0F: "TAB",
    0x10: "Q", 0x11: "W", 0x12: "E", 0x13: "R", 0x14: "T", 0x15: "Y",
    0x16: "U", 0x17: "I", 0x18: "O", 0x19: "P", 0x1A: "LBRACKET",
    0x1B: "RBRACKET", 0x1C: "ENTER", 0x1D: "LCTRL",
    0x1E: "A", 0x1F: "S", 0x20: "D", 0x21: "F", 0x22: "G", 0x23: "H",
    0x24: "J", 0x25: "K", 0x26: "L", 0x27: "SEMICOLON", 0x28: "QUOTE",
    0x29: "GRAVE", 0x2A: "LSHIFT", 0x2B: "BACKSLASH",
    0x2C: "Z", 0x2D: "X", 0x2E: "C", 0x2F: "V", 0x30: "B", 0x31: "N",
    0x32: "M", 0x33: "COMMA", 0x34: "DOT", 0x35: "SLASH", 0x36: "RSHIFT",
    0x37: "KP_STAR", 0x38: "LALT", 0x39: "SPACE", 0x3A: "CAPSLOCK",
    0x3B: "F1", 0x3C: "F2", 0x3D: "F3", 0x3E: "F4", 0x3F: "F5", 0x40: "F6",
    0x41: "F7", 0x42: "F8", 0x43: "F9", 0x44: "F10", 0x45: "NUMLOCK",
    0x46: "SCROLLLOCK", 0x47: "KP7", 0x48: "KP8", 0x49: "KP9",
    0x4A: "KP_MINUS", 0x4B: "KP4", 0x4C: "KP5", 0x4D: "KP6", 0x4E: "KP_PLUS",
    0x4F: "KP1", 0x50: "KP2", 0x51: "KP3", 0x52: "KP0", 0x53: "KP_DOT",
    0x57: "F11", 0x58: "F12",
})
_scan(True, {
    0x1C: "KP_ENTER", 0x1D: "RCTRL", 0x35: "KP_SLASH", 0x37: "PRINTSCREEN",
    0x38: "RALT", 0x47: "HOME", 0x48: "UP", 0x49: "PAGEUP", 0x4B: "LEFT",
    0x4D: "RIGHT", 0x4F: "END", 0x50: "DOWN", 0x51: "PAGEDOWN",
    0x52: "INSERT", 0x53: "DELETE", 0x5B: "LGUI", 0x5C: "RGUI",
})
SCAN_TO_HID[(False, 0x56)] = 0x64       # la tecla extra del teclado ISO (<>)
SCAN_TO_HID[(True, 0x5D)] = 0x65        # tecla de menú contextual

# Virtual-Keys de Tk/Windows que son modificadores: se resuelven aparte.
VK_SHIFT, VK_CONTROL, VK_MENU = 16, 17, 18
MODIFIER_VKS = (VK_SHIFT, VK_CONTROL, VK_MENU)
EXTENDED_STATE_BIT = 0x40000            # `event.state` de Tk en Windows

# Sin ctypes de Windows: por nombre de keysym. Solo cubre lo común.
KEYSYM_TO_NAME = {
    "return": "ENTER", "escape": "ESC", "backspace": "BACKSPACE", "tab": "TAB",
    "space": "SPACE", "left": "LEFT", "right": "RIGHT", "up": "UP",
    "down": "DOWN", "home": "HOME", "end": "END", "prior": "PAGEUP",
    "next": "PAGEDOWN", "insert": "INSERT", "delete": "DELETE",
    "caps_lock": "CAPSLOCK", "shift_l": "LSHIFT", "shift_r": "RSHIFT",
    "control_l": "LCTRL", "control_r": "RCTRL", "alt_l": "LALT",
    "alt_r": "RALT", "win_l": "LGUI", "win_r": "RGUI", "super_l": "LGUI",
    "super_r": "RGUI", "minus": "MINUS", "equal": "EQUAL",
    "bracketleft": "LBRACKET", "bracketright": "RBRACKET",
    "backslash": "BACKSLASH", "semicolon": "SEMICOLON", "apostrophe": "QUOTE",
    "grave": "GRAVE", "comma": "COMMA", "period": "DOT", "slash": "SLASH",
}


def usage_from_scancode(scancode: int, extended: bool) -> int | None:
    return SCAN_TO_HID.get((extended, scancode))


def usage_from_keysym(keysym: str) -> int | None:
    """Respaldo sin scancodes: por nombre de keysym (letras, dígitos, F1-F12...)."""
    name = KEYSYM_TO_NAME.get(keysym.lower())
    if name is None:
        candidate = keysym.upper()
        name = candidate if candidate in hid_keys.KEY_NAMES else None
    return hid_keys.KEY_NAMES.get(name) if name else None


def windows_scancode_of(virtual_key: int) -> int:
    """Scancode físico de una Virtual-Key en el layout activo (0 si no hay)."""
    import ctypes
    return ctypes.windll.user32.MapVirtualKeyW(virtual_key, 0)


def windows_modifiers() -> set[int]:
    """Usage IDs de los modificadores pulsados AHORA, izquierdos y derechos."""
    import ctypes
    pressed = set()
    for virtual_key, name in ((0xA0, "LSHIFT"), (0xA1, "RSHIFT"), (0xA2, "LCTRL"),
                              (0xA3, "RCTRL"), (0xA4, "LALT"), (0xA5, "RALT"),
                              (0x5B, "LGUI"), (0x5C, "RGUI")):
        if ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000:
            pressed.add(hid_keys.usage_of(name))
    return pressed


def host_usage(keycode: int, state: int, keysym: str, *,
               scancode_of: Callable[[int], int] | None = None) -> int | None:
    """Usage ID de un evento de tecla de Tk, o None si no se sabe traducir.

    Los modificadores (Virtual-Key 16, 17 y 18) devuelven None: su estado se
    toma de `windows_modifiers()` o, sin Windows, de su keysym (`HostKeyboard`).
    """
    if keycode in MODIFIER_VKS:
        return None
    if scancode_of is not None:
        scancode = scancode_of(keycode)
        if scancode:
            usage = usage_from_scancode(scancode, bool(state & EXTENDED_STATE_BIT))
            if usage is not None:
                return usage
    return usage_from_keysym(keysym)


class HostKeyboard:
    """Teclas pulsadas del anfitrión -> reports de estado completo.

    `emit(pressed)` se llama con el conjunto completo de Usage IDs pulsados
    cada vez que cambia. No sabe de Tk: la ventana le pasa pulsaciones y
    liberaciones ya traducidas.
    """

    ALTGR_WINDOW_MS = 5

    def __init__(self, emit: Callable[[frozenset], None]):
        self.emit = emit
        self.pressed: set[int] = set()
        self._since: dict[int, int] = {}
        # AltGr retirado: mientras dure, el Control_L falso que el SO sigue
        # contando como pulsado no vuelve a entrar.
        self._altgr = False

    def _changed(self, before: set[int]) -> None:
        if self.pressed != before:
            self.emit(frozenset(self.pressed))

    def press(self, usage: int, time_ms: int = 0) -> None:
        if usage in self.pressed:           # autorepeat: no es una pulsación nueva
            return
        before = set(self.pressed)
        self.pressed.add(usage)
        self._since[usage] = time_ms
        if usage == hid_keys.usage_of("RALT"):
            # AltGr = Control_L falso + Alt_R casi a la vez (§ docstring).
            lctrl = hid_keys.usage_of("LCTRL")
            if lctrl in self.pressed and time_ms - self._since.get(lctrl, -10**9) \
                    <= self.ALTGR_WINDOW_MS:
                self.pressed.discard(lctrl)
        self._changed(before)

    def release(self, usage: int) -> None:
        before = set(self.pressed)
        self.pressed.discard(usage)
        self._changed(before)

    def set_modifiers(self, modifiers: set[int]) -> None:
        """Sustituye los modificadores pulsados por los que se leen del SO."""
        before = set(self.pressed)
        keep = {u for u in self.pressed
                if not hid_keys.MODIFIER_FIRST <= u <= hid_keys.MODIFIER_LAST}
        wanted = {u for u in modifiers
                  if hid_keys.MODIFIER_FIRST <= u <= hid_keys.MODIFIER_LAST}
        ralt, lctrl = hid_keys.usage_of("RALT"), hid_keys.usage_of("LCTRL")
        if ralt not in wanted:
            self._altgr = False
        elif lctrl in wanted and (self._altgr or (ralt not in before
                                                  and lctrl not in before)):
            # AltGr: Alt derecho y Control izquierdo aparecen juntos. El Control
            # es el falso del SO y se retira mientras dure el Alt derecho.
            self._altgr = True
            wanted.discard(lctrl)
        self.pressed = keep | wanted
        self._changed(before)

    def release_all(self) -> None:
        """Pérdida de foco: lo que estuviera pulsado ya no llegará a soltarse."""
        before = set(self.pressed)
        self.pressed.clear()
        self._changed(before)


class HostMouse:
    """Movimiento y botones del ratón del anfitrión -> reports.

    Tk da posiciones absolutas dentro de la ventana; INPUT quiere deltas. Los
    deltas se acumulan hasta `drain()`, que es la fusión de movimientos
    consecutivos: el USB real llega a unos 125 Hz, no a un evento por píxel.

    Un ratón real no deja de informar de su movimiento al salir de la ventana,
    y un programa con un pincel o un cursor propio lo necesita para no
    descolocarse. Por eso la salida y la reentrada cuentan: al volver a entrar
    se entrega el desplazamiento neto entre por donde salió y por donde entra.
    Con `origin`, el ratón se supone al principio en ese punto (el centro de la
    ventana, donde un programa suele arrancar su cursor), y la primera entrada
    entrega lo que hay de ahí al puntero.
    """

    TK_BUTTONS = {1: 0, 3: 1, 2: 2}         # Tk: 1 izq., 2 central, 3 der.

    def __init__(self, origin: tuple[int, int] | None = None):
        self.buttons = 0
        self.dx = 0
        self.dy = 0
        self._last: tuple[int, int] | None = origin

    def _move_to(self, x: int, y: int) -> None:
        if self._last is not None:
            self.dx += x - self._last[0]
            self.dy += y - self._last[1]
        self._last = (x, y)

    def enter(self, x: int, y: int) -> None:
        self._move_to(x, y)                 # el recorrido de fuera, de golpe

    def leave(self, x: int | None = None, y: int | None = None) -> None:
        """El puntero sale; (x, y) es por dónde, y es lo último que se sabe."""
        if x is not None and y is not None:
            self._move_to(x, y)

    def motion(self, x: int, y: int) -> None:
        self._move_to(x, y)

    def button(self, tk_number: int, down: bool) -> None:
        bit = self.TK_BUTTONS.get(tk_number)
        if bit is None:
            return
        self.buttons = (self.buttons | (1 << bit)) if down else (self.buttons & ~(1 << bit))

    def release_all(self) -> None:
        self.buttons = 0

    def drain(self, previous_buttons: int) -> tuple[int, int, int] | None:
        """(botones, dx, dy) si hay algo que reportar desde el último drain."""
        if not (self.dx or self.dy) and self.buttons == previous_buttons:
            return None
        report = (self.buttons, self.dx, self.dy)
        self.dx = self.dy = 0
        return report


def default_scancode_of() -> Callable[[int], int] | None:
    """El adaptador de scancodes del SO, o None si no lo hay."""
    if sys.platform != "win32":
        return None
    try:
        windows_scancode_of(65)
    except (AttributeError, OSError):
        return None
    return windows_scancode_of
