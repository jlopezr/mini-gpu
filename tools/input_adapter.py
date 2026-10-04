"""El adaptador de INPUT: del teclado y el ratón del PC a eventos para la placa.

`input_registers.v` solo guarda (mmio.md Apéndice A): el que calcula los eventos
es el adaptador que va delante, y con el monitor como fuente ese adaptador es
este módulo. Reutiliza las reglas de orden de `InputDevice.keyboard_events` y
`mouse_events`, que son las del oráculo, de modo que la placa recibe
exactamente lo que recibiría el simulador.

Lo que añade, y es política del anfitrión y no del dispositivo:

  - Control de flujo. Cada respuesta del monitor dice cuántos huecos le quedan a
    la FIFO. Las teclas y los botones NO se pueden perder, así que esperan en una
    cola local; el movimiento del ratón se FUNDE mientras no hay sitio, como hace
    `SimDisplay._hold_mouse`, y sale con el recorrido exacto.
  - Una ida y vuelta por el monitor cuesta ~16 ms por el latency timer del FTDI,
    así que se manda UN comando por vuelta del bucle, con todas las palabras que
    quepan, y no uno por evento.
  - Al salir, las liberaciones de todo lo que siga pulsado y después la
    presencia a cero (§25.11): la placa no se queda con teclas pulsadas.

No sabe de Tk ni de la placa: recibe diccionarios (los de `screen_window.py`) y
habla con un cliente que tenga `send_input_events` y `set_input_presence`
(`InputMixin`). Por eso se prueba entero sin ventana y sin hardware.
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.sim_devices import InputDevice  # noqa: E402

# Huecos que el movimiento del ratón deja libres para teclas y botones, que no
# se pueden perder. El movimiento solo entra si sobra más que esto.
MOUSE_ROOM = 2
# Cada cuánto se sondea la FIFO cuando no cabe nada: la CPU la va vaciando.
PROBE_PERIOD = 0.005
# Lo máximo que cabe en un movimiento (12 bits con signo). Basta para cruzar la
# pantalla de 640x480 de una vez.
HOME_SWEEP = 2047


class InputAdapter:
    def __init__(self, client, clock=time.monotonic):
        self.client = client
        self.clock = clock
        self.keys = 0                   # último report de teclado (bitmap de 256 bits)
        self.buttons = 0                # último report de botones
        self.dx = 0                     # movimiento aún sin mandar
        self.dy = 0
        self.queue: list[int] = []      # palabras que no se pueden perder, en orden
        self.free: int | None = None    # huecos libres según la última respuesta
        self._last_probe = float("-inf")
        self.connected = False

    # ---- ciclo de vida --------------------------------------------------------

    def connect(self) -> None:
        """Presencia de teclado y ratón. Parten del estado vacío (§25.11)."""
        self.free = self.client.set_input_presence(True, True)
        self.connected = True

    def home(self, x: int, y: int) -> None:
        """Deja el puntero de la placa en (x, y) sea cual sea su posición.

        El ratón de INPUT es relativo, y el programa de la placa sigue vivo entre
        una sesión y otra: conserva el puntero donde lo dejó la anterior, mientras
        que la ventana de captura supone que empieza en su centro. Sin esto, cada
        vez que se sale y se vuelve a entrar queda un desfase. Se barre hacia la
        esquina (0, 0), donde cualquier programa que recorte su cursor a la
        pantalla lo deja, y de ahí se va a (x, y), con lo que el punto de partida
        es conocido.
        """
        self._commit_move()
        self.dx = -HOME_SWEEP
        self.dy = -HOME_SWEEP
        self._commit_move()
        self.dx = x
        self.dy = y

    def close(self, timeout: float = 2.0) -> None:
        """Libera lo pulsado, espera a que salga y quita la presencia."""
        if not self.connected:
            return
        self.dx = self.dy = 0           # el movimiento pendiente ya no importa
        self.queue += InputDevice.keyboard_events(self.keys, 0)
        self.queue += InputDevice.mouse_events(self.buttons, 0)
        self.keys = self.buttons = 0
        deadline = self.clock() + timeout
        try:
            while self.queue and self.clock() < deadline:
                if not self.pump():
                    time.sleep(PROBE_PERIOD)
        except KeyboardInterrupt:
            pass                        # otro Ctrl+C: dejar de esperar, pero quitar la presencia
        self.free = self.client.set_input_presence(False, False)
        self.connected = False

    # ---- entrada: lo que cuenta la ventana ------------------------------------

    def handle(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "keys":
            self.keys_report(event.get("pressed", ()))
        elif kind == "mouse":
            self.mouse_report(int(event.get("buttons", 0)),
                              int(event.get("dx", 0)), int(event.get("dy", 0)))

    def keys_report(self, pressed) -> None:
        mask = 0
        for usage in pressed:
            if 1 <= usage <= 0xFF:
                mask |= 1 << usage
        self.queue += InputDevice.keyboard_events(self.keys, mask)
        self.keys = mask

    def mouse_report(self, buttons: int, dx: int, dy: int) -> None:
        if buttons != self.buttons:
            # Lo que se movió ANTES del clic tiene que salir antes que el clic:
            # si no, el botón se pulsaría en un punto que el programa aún no ha
            # visto.
            self._commit_move()
            self.queue += InputDevice.mouse_events(self.buttons, buttons)
            self.buttons = buttons
        self.dx += dx
        self.dy += dy

    def _commit_move(self) -> None:
        self.queue += InputDevice.mouse_events(self.buttons, self.buttons,
                                               self.dx, self.dy)
        self.dx = self.dy = 0

    # ---- salida: un comando por vuelta ----------------------------------------

    @property
    def pending(self) -> bool:
        return bool(self.queue or self.dx or self.dy)

    def pump(self) -> bool:
        """Manda como mucho UN comando. Devuelve si habló con la placa."""
        if not self.pending or not self.connected:
            return False
        if self.free is None:
            self.free = self.client.send_input_events([])
            return True
        words = self._next_words()
        if words:
            self.free = self.client.send_input_events(words)
            return True
        # No cabe nada: preguntar cuántos huecos hay, sin saturar el enlace.
        now = self.clock()
        if now - self._last_probe >= PROBE_PERIOD:
            self._last_probe = now
            self.free = self.client.send_input_events([])
            return True
        return False

    def _next_words(self) -> list[int]:
        depth = InputDevice.FIFO_DEPTH
        if self.queue:
            count = min(len(self.queue), self.free, depth)
            words = self.queue[:count]
            del self.queue[:count]
            return words
        allowed = min(self.free - MOUSE_ROOM, depth)
        if allowed <= 0:
            return []
        words = InputDevice.mouse_events(self.buttons, self.buttons,
                                         self.dx, self.dy)[:allowed]
        for word in words:
            move = InputDevice.decode_event(word)
            self.dx -= move["dx"]
            self.dy -= move["dy"]
        return words


def run_session(client, source, status=None, home: bool = True) -> None:
    """Conecta, atiende a `source` hasta F12 o hasta cerrar la ventana, y
    desconecta. `source.poll(timeout)` devuelve la lista de eventos pendientes.

    Con `home`, y si la fuente dice dónde supone el ratón al empezar
    (`source.origin`), el puntero de la placa se lleva allí al conectar."""
    adapter = InputAdapter(client)
    adapter.connect()
    origin = getattr(source, "origin", None)
    if home and origin is not None:
        adapter.home(*origin)
    try:
        running = True
        while running:
            for event in source.poll(0.01 if not adapter.pending else 0.0):
                if event.get("event") in ("interrupt", "closed"):
                    running = False
                    break
                adapter.handle(event)
            if running and not adapter.pump() and adapter.pending:
                time.sleep(PROBE_PERIOD)
            if status is not None:
                status(adapter)
    except KeyboardInterrupt:
        # Ctrl+C sale igual que F12: se sueltan las teclas y se quita la presencia.
        print("\nCtrl+C: soltando teclas y desconectando INPUT...", file=sys.stderr)
    finally:
        adapter.close()


class WindowSource:
    """La ventana de captura (`screen_window.py --panel`) como fuente de eventos."""

    # Escala 1: la ventana mide 640x480, o sea lo que sale por HDMI, y un pixel
    # del ratón es un movimiento de INPUT. `input_paint.asm` cuenta en medios
    # pixeles de framebuffer (320x240) precisamente porque la pantalla es el
    # doble, así que el pincel sigue al puntero a su velocidad.
    def __init__(self, scale: int = 1):
        from tools.screen import SCREEN_SIZE
        # Donde la ventana supone el ratón al empezar: su centro (screen_window.py).
        self.origin = (SCREEN_SIZE[0] * scale // 2, SCREEN_SIZE[1] * scale // 2)
        command = [sys.executable, str(ROOT / "tools" / "screen_window.py"),
                   "--panel", "--input", "--scale", str(scale)]
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            bufsize=1)
        self.events: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.process.stdout:
            try:
                self.events.put(json.loads(line))
            except json.JSONDecodeError:
                if line.strip():
                    print(f"ventana: {line.strip()}", file=sys.stderr)
        self.events.put({"event": "closed"})

    def poll(self, timeout: float) -> list[dict]:
        found = []
        try:
            found.append(self.events.get(timeout=timeout) if timeout
                         else self.events.get_nowait())
            while True:
                found.append(self.events.get_nowait())
        except queue.Empty:
            pass
        return found

    def panel(self, text: str) -> None:
        try:
            self.process.stdin.write(json.dumps({"panel": text}) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def close(self) -> None:
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
