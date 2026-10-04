"""Cosas de anfitrión que comparten los simuladores interactivos.

* `stop_machine`: parar un simulador desde fuera de su bucle (cerrar la
  ventana, F12, Ctrl+C).
* `Keyboard`: teclas sueltas del terminal, sin eco y sin esperar a Enter.
* `SerialTty`: el terminal como extremo del puerto serie (`--serial-tty`). Lo
  que el programa escribe en `SERIAL.DATA` sale por stdout y lo que se teclea
  entra por RX, como `run-board --interactive` hace con la placa. Es la forma
  de probar en el simulador un programa que habla por UART.
"""
from __future__ import annotations

import atexit
import sys

CTRL_C = b"\x03"


def stop_machine(machine) -> None:
    """Pide que `machine` pare en su próxima instrucción."""
    if machine is None:
        return
    if hasattr(machine, "peripheral_halted"):
        machine.peripheral_halted = True        # GPU
    else:
        machine.halted = True                   # CPU


class Keyboard:
    """Teclas sueltas, sin eco y sin esperar a Enter. Windows y POSIX."""

    def __enter__(self):
        if sys.platform == "win32":
            import msvcrt
            self._msvcrt = msvcrt
        else:
            import termios
            import tty
            self._termios = termios
            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc):
        if sys.platform != "win32":
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._saved)

    def read(self) -> bytes:
        """Los bytes pendientes; vacío si no se ha pulsado nada."""
        out = bytearray()
        if sys.platform == "win32":
            while self._msvcrt.kbhit():
                char = self._msvcrt.getwch()
                if char in ("\x00", "\xe0"):    # tecla de función o flecha: su 2.º byte
                    self._msvcrt.getwch()
                    continue
                out += char.encode("latin-1", "replace")
        else:
            import select
            while select.select([sys.stdin], [], [], 0)[0]:
                data = sys.stdin.buffer.read1(64)
                if not data:
                    break
                out += data
        return bytes(out)


class SerialTty:
    """El terminal como extremo del puerto serie de un simulador.

    `SerialDevice.tick` llama a `poll` cada cierto número de instrucciones y a
    `write` con lo que el programa ha enviado. Las teclas que no caben en la
    cola de entrada esperan en `pending`: perderlas sería distinto de la placa,
    donde el control de flujo del host lo evita.
    """

    def __init__(self):
        self.machine = None
        self.pending = b""
        self.keyboard: Keyboard | None = None
        self.interrupted = False

    def bind(self, machine) -> None:
        self.machine = machine

    def start(self) -> None:
        self.keyboard = Keyboard().__enter__()
        atexit.register(self.close)
        sys.stderr.write("Serie por terminal: lo que teclees llega al programa; "
                         "Ctrl+C sale.\n")
        sys.stderr.flush()

    def close(self) -> None:
        keyboard, self.keyboard = self.keyboard, None
        if keyboard is not None:
            keyboard.__exit__(None, None, None)

    def write(self, data: bytes) -> None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def poll(self, serial) -> None:
        if self.keyboard is None:
            return
        keys = self.keyboard.read()
        if CTRL_C in keys:
            self.interrupted = True
            stop_machine(self.machine)
            return
        self.pending += keys
        if self.pending:
            room = max(0, serial.depth - len(serial.rx))
            accepted = serial.push(self.pending[:room])
            self.pending = self.pending[accepted:]
