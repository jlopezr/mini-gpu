"""Vectores diferenciales de `input_registers.v`, generados con `InputDevice`.

El oraculo es el simulador (`tools/sim_devices.py`): aqui se ejecutan secuencias
de operaciones sobre un `InputDevice` y se anota, junto a cada operacion, lo que
el RTL tiene que contestar. `30.fpga-cpu-console/input_registers_tb.v` lee el
fichero y reproduce cada linea por el puerto de eventos y por MMIO, comparando
palabra a palabra.

Cada linea son 18 digitos hexadecimales: `OP(2) ARG(8) EXP(8)`.

    00 fin
    01 EVENT          arg = palabra de evento
    02 PRESENCE       arg = bit0 teclado, bit1 raton (como el byte de INPUT_PRESENCE)
    03 READ           arg = offset;  exp = valor leido por MMIO
    04 WRITE          arg = valor escrito en EVENT_CTRL (valido)
    05 WRITE_BAD      arg = valor con bits reservados: error y sin efecto
    06 FREE           exp = huecos libres que el RTL debe anunciar
    07 EVENT_POP      evento en el MISMO ciclo que el pop de EVENT_DATA; exp = lo leido
    08 EVENT_FLUSH    evento en el mismo ciclo que un FLUSH (§25.9: gana FLUSH)
    09 EVENT_CLEAR    evento en el mismo ciclo que un CLEAR_OVERFLOW
    0A WRITE_PARTIAL  escritura valida pero con mascara parcial: error y sin efecto

Los casos de colision (07-09) se resuelven en el oraculo ordenando las llamadas
que ya existen --no hace falta un `InputDevice` nuevo--, y el orden elegido es la
regla de §25.5 y §25.9: el pop libera hueco ANTES del push, FLUSH gana al push y
no produce overflow, y una perdida gana a CLEAR_OVERFLOW.

Regenerar:

    python -m tools.gen_input_vectors

`x.tests/test_input_vectors.py` comprueba que el fichero versionado coincide.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.sim_devices import InputDevice as D  # noqa: E402

OUTPUT = ROOT / "30.fpga-cpu-console" / "input_vectors.hex"

OP_END, OP_EVENT, OP_PRESENCE, OP_READ, OP_WRITE, OP_WRITE_BAD, OP_FREE, \
    OP_EVENT_POP, OP_EVENT_FLUSH, OP_EVENT_CLEAR, OP_WRITE_PARTIAL = range(11)

READ_OFFSETS = (D.EVENT_DATA, D.STATUS, *(D.KEY_STATE0 + 4 * i for i in range(8)),
                D.MOUSE_BUTTONS)


class Recorder:
    """Ejecuta cada operacion sobre el oraculo y apunta la linea del fichero."""

    def __init__(self):
        self.device = D()
        self.lines: list[tuple[int, int, int]] = []

    def _add(self, op: int, arg: int = 0, exp: int = 0) -> None:
        self.lines.append((op, arg, exp))

    def event(self, word: int) -> None:
        self.device.apply_event(word)
        self._add(OP_EVENT, word)

    def presence(self, keyboard: bool, mouse: bool) -> None:
        self.device.set_presence(keyboard, mouse)
        self._add(OP_PRESENCE, int(keyboard) | (int(mouse) << 1))

    def read(self, offset: int) -> int:
        value = self.device.read(offset)
        self._add(OP_READ, offset, value)
        return value

    def write(self, value: int) -> None:
        self.device.write(D.EVENT_CTRL, value)
        self._add(OP_WRITE, value)

    def write_bad(self, value: int) -> None:
        # El oraculo lanza y no cambia nada; el RTL da error y tampoco.
        try:
            self.device.write(D.EVENT_CTRL, value)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"EVENT_CTRL {value:#x} deberia dar error")
        self._add(OP_WRITE_BAD, value)

    def write_partial(self, value: int) -> None:
        self._add(OP_WRITE_PARTIAL, value)

    def free(self) -> None:
        self._add(OP_FREE, 0, D.FIFO_DEPTH - len(self.device.fifo))

    def event_pop(self, word: int) -> None:
        value = self.device.read(D.EVENT_DATA)
        self.device.apply_event(word)
        self._add(OP_EVENT_POP, word, value)

    def event_flush(self, word: int) -> None:
        overflow = self.device.overflow
        self.device.apply_event(word)       # STATE se actualiza siempre
        self.device.fifo.clear()
        self.device.overflow = overflow     # FLUSH no produce overflow
        self._add(OP_EVENT_FLUSH, word)

    def event_clear(self, word: int) -> None:
        self.device.write(D.EVENT_CTRL, D.CTRL_CLEAR_OVERFLOW)
        self.device.apply_event(word)       # si se pierde, OVERFLOW vuelve a uno
        self._add(OP_EVENT_CLEAR, word)

    def check_all(self) -> None:
        """Lee STATUS, KEY_STATE0..7 y MOUSE_BUTTONS (nada de ello consume)."""
        for offset in READ_OFFSETS[1:]:
            self.read(offset)
        self.free()

    def drain(self) -> None:
        while self.device.fifo:
            self.read(D.EVENT_DATA)
        self.read(D.EVENT_DATA)             # vacia: cero y sin efecto
        self.read(D.STATUS)
        self.free()


A, B, SPACE = 0x04, 0x05, 0x2C


def scenario_state(r: Recorder) -> None:
    """STATE derivado de cada tipo de evento."""
    r.read(D.STATUS)
    r.presence(True, True)
    r.read(D.STATUS)
    r.event(D.key_event(A, True, 0x00))
    r.event(D.key_event(SPACE, True, 0x00))
    r.event(D.key_event(0xFF, True, 0x00))
    r.event(D.key_event(0x52, True, 0x00))
    r.check_all()
    r.event(D.key_event(0, False, 0x82))            # modificadores: 0xE1 y 0xE7
    r.check_all()
    r.event(D.key_event(A, False, 0x82))            # soltar una tecla normal
    r.event(D.key_event(0, False, 0x01))            # solo 0xE0
    r.check_all()
    r.event(D.mouse_button_event(0, True))
    r.event(D.mouse_button_event(31, True))
    r.event(D.mouse_button_event(40, True))         # no cabe en MOUSE_BUTTONS
    r.check_all()
    r.event(D.mouse_move_event(5, -7))              # el movimiento no toca STATE
    r.event(D.mouse_button_event(0, False))
    r.check_all()
    r.event(0x7F00_0001)                            # TYPE reservado: solo se encola
    r.event(D.key_event(0xE3, True, 0x00))          # KEY dentro de 0xE0..0xE7
    r.check_all()
    r.drain()


def scenario_overflow(r: Recorder) -> None:
    """17 eventos, recuperacion y STATE al dia mientras la FIFO esta llena."""
    r.write(D.CTRL_FLUSH | D.CTRL_CLEAR_OVERFLOW)
    for i in range(16):
        r.event(D.mouse_move_event(i + 1, -i))
    r.free()
    r.event(D.mouse_move_event(100, 100))           # el 17: se pierde
    r.read(D.STATUS)
    r.event(D.key_event(B, True, 0x00))             # llena: STATE se actualiza
    r.event(D.mouse_button_event(2, True))
    r.check_all()
    for _ in range(3):
        r.read(D.EVENT_DATA)
    r.read(D.STATUS)                                # OVERFLOW sigue pegajoso
    r.event(D.mouse_move_event(7, 7))               # ya entra
    r.free()
    r.write(D.CTRL_CLEAR_OVERFLOW)
    r.read(D.STATUS)
    r.drain()
    r.event(D.key_event(B, False, 0x00))
    r.event(D.mouse_button_event(2, False))
    r.drain()


def scenario_collisions(r: Recorder) -> None:
    # FLUSH contra PUSH, con la FIFO a medias y llena.
    for i in range(3):
        r.event(D.mouse_move_event(i, i))
    r.event_flush(D.key_event(A, True, 0x00))
    r.check_all()
    for i in range(16):
        r.event(D.mouse_move_event(i, i))
    r.event_flush(D.key_event(A, False, 0x00))
    r.check_all()
    # POP + PUSH con la FIFO llena: sin overflow.
    r.write(D.CTRL_FLUSH | D.CTRL_CLEAR_OVERFLOW)
    for i in range(16):
        r.event(D.mouse_move_event(i + 1, 0))
    r.event_pop(D.mouse_move_event(99, 0))
    r.check_all()
    r.event_pop(D.mouse_move_event(98, 0))
    r.check_all()
    # POP + PUSH con la FIFO vacia.
    r.drain()
    r.event_pop(D.mouse_move_event(1, 1))
    r.check_all()
    r.drain()
    # CLEAR_OVERFLOW contra una perdida nueva y contra un push normal.
    for i in range(17):
        r.event(D.mouse_move_event(i, 0))
    r.read(D.STATUS)
    r.event_clear(D.mouse_move_event(55, 0))        # se pierde: OVERFLOW queda a uno
    r.read(D.STATUS)
    r.write(D.CTRL_FLUSH)
    r.event_clear(D.mouse_move_event(56, 0))        # entra: OVERFLOW se borra
    r.read(D.STATUS)
    r.drain()
    # Ambos bits a la vez.
    for i in range(17):
        r.event(D.mouse_move_event(i, 0))
    r.write(D.CTRL_FLUSH | D.CTRL_CLEAR_OVERFLOW)
    r.read(D.STATUS)
    r.write(0)                                      # escribir cero no hace nada
    r.read(D.STATUS)


def scenario_presence(r: Recorder) -> None:
    r.presence(True, True)
    r.event(D.key_event(A, True, 0x02))
    r.event(D.key_event(0, False, 0x02))
    r.event(D.mouse_button_event(1, True))
    r.check_all()
    r.presence(False, True)                         # teclado fuera: su STATE a cero
    r.check_all()
    r.presence(True, False)                         # raton fuera, teclado dentro
    r.check_all()
    r.presence(False, False)
    r.check_all()
    r.presence(True, True)
    r.check_all()
    r.drain()


def scenario_errors(r: Recorder) -> None:
    for i in range(4):
        r.event(D.mouse_move_event(i, 0))
    r.event(D.key_event(A, True, 0x00))
    r.read(D.STATUS)
    for bad in (0x4, 0x8, 0x8000_0000, 0xFFFF_FFFF, 0x0000_0007, 0x1_0000):
        r.write_bad(bad)
        r.read(D.STATUS)                            # nada se ejecuto
    r.write_partial(D.CTRL_FLUSH)
    r.read(D.STATUS)
    r.check_all()
    r.drain()


def scenario_random(r: Recorder, seed: int, steps: int) -> None:
    rng = random.Random(seed)
    usages = (A, B, SPACE, 0x52, 0xFF, 0x1F, 0x20, 0xE8, 0xF0)
    # Fases: unas llenan la FIFO, otras la vaciaban, para pisar el overflow.
    for step in range(steps):
        fase_llena = (step // 40) % 2 == 0
        roll = rng.random()
        if roll < (0.55 if fase_llena else 0.20):
            kind = rng.randrange(7)
            if kind == 0:
                word = D.key_event(rng.choice(usages), rng.random() < 0.5,
                                   rng.randrange(256))
            elif kind == 1:
                word = D.key_event(0, False, rng.randrange(256))
            elif kind == 2:
                word = D.mouse_button_event(rng.choice((0, 1, 2, 7, 31, 32, 200)),
                                            rng.random() < 0.5)
            elif kind == 3:
                word = D.key_event(rng.randrange(0xE0, 0xE8), rng.random() < 0.5, 0)
            elif kind == 4:
                word = (rng.randrange(3, 256) << 24) | rng.randrange(1 << 24)
            else:
                word = D.mouse_move_event(rng.randrange(-2048, 2048),
                                          rng.randrange(-2048, 2048))
            r.event(word)
        elif roll < 0.80:
            r.read(D.EVENT_DATA)
        elif roll < 0.88:
            r.read(rng.choice(READ_OFFSETS))
        elif roll < 0.91:
            r.write(rng.randrange(4))
        elif roll < 0.93:
            r.presence(rng.random() < 0.7, rng.random() < 0.7)
        elif roll < 0.94:
            r.write_bad(rng.choice((0x4, 0x100, 0xFFFF_FFFC, 0x8000_0001)))
        elif roll < 0.96:
            r.event_pop(D.mouse_move_event(rng.randrange(-5, 5), 3))
        elif roll < 0.98:
            r.event_flush(D.key_event(rng.choice(usages), rng.random() < 0.5, 0))
        else:
            r.event_clear(D.mouse_button_event(rng.randrange(4), rng.random() < 0.5))
        r.free()
        if step % 25 == 24:
            r.check_all()


def build_vectors() -> list[tuple[int, int, int]]:
    r = Recorder()
    scenario_state(r)
    scenario_overflow(r)
    scenario_collisions(r)
    scenario_presence(r)
    scenario_errors(r)
    scenario_random(r, seed=25, steps=3000)
    r._add(OP_END)
    return r.lines


def render(lines) -> str:
    return "".join(f"{op:02x}{arg:08x}{exp:08x}\n" for op, arg, exp in lines)


def main() -> None:
    lines = build_vectors()
    OUTPUT.write_text(render(lines), encoding="ascii", newline="\n")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(lines)} lineas")


if __name__ == "__main__":
    main()
