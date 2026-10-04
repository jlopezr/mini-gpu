"""La ventana de un simulador, vista desde el simulador.

`SimDisplay` abre `tools/screen_window.py` y hace tres cosas, todas desde el
hilo del simulador, que es el único que toca el estado:

* **Refrescar:** cada cierto tiempo de pared manda un `snapshot` de la pantalla
  (`tools/screen.py`) --y solo si cambió--, con el simulador corriendo.
* **Entrada:** aplica a `InputDevice` los reports de teclado y ratón que manda
  la ventana. Un hilo lector los deja en una cola y `poll` los consume: la cola
  es el único punto de encuentro entre hilos.
* **Cierre:** si se cierra la ventana, desconecta teclado y ratón (con sus
  liberaciones, §25.11) y para el simulador; F12 también lo para.

`InputDevice.tick` llama a `poll` cada `every` instrucciones, de modo que no
hace falta tocar el bucle de ejecución de ningún simulador.
"""
from __future__ import annotations

import base64
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from tools import screen

ROOT = Path(__file__).resolve().parents[1]


class SimDisplay:
    def __init__(self, font: Path, scale: int = 1, refresh_hz: float = 15.0,
                 every: int = 2000):
        self.font = Path(font)
        self.scale = scale
        self.period = 1.0 / refresh_hz
        self.every = every
        self.machine = None
        self.process: subprocess.Popen | None = None
        self.events: queue.Queue = queue.Queue()
        self.closed = False
        self.interrupted = False
        self._last_snapshot = None
        self._last_send = 0.0
        self._last_title = 0.0

    # ---- ciclo de vida -------------------------------------------------------

    def bind(self, machine) -> None:
        self.machine = machine

    def start(self, device) -> None:
        """Abre la ventana y conecta teclado y ratón."""
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "tools" / "screen_window.py"), str(self.font),
             "--input", "--scale", str(self.scale)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self._read_events, args=(self.process,), daemon=True).start()
        device.connect_keyboard()
        device.connect_mouse()
        self._send_screen(force=True)

    def _read_events(self, process) -> None:
        for line in process.stdout:
            try:
                self.events.put(json.loads(line))
            except json.JSONDecodeError:
                if line.strip():
                    print(f"ventana: {line.strip()}", file=sys.stderr)
        self.events.put({"event": "closed"})

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    # ---- desde el hilo del simulador ----------------------------------------

    def poll(self, device) -> None:
        """Entrada pendiente, y refresco si toca. Barato si no hay nada que hacer."""
        self.apply_events(device)
        if not self.closed:
            self._send_screen()

    def apply_events(self, device) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            kind = event.get("event")
            if kind == "keys" and device.keyboard_present:
                device.keyboard_report(set(event.get("pressed", ())))
            elif kind == "mouse" and device.mouse_present:
                device.mouse_report(int(event.get("buttons", 0)),
                                    int(event.get("dx", 0)), int(event.get("dy", 0)))
            elif kind == "interrupt":
                self.interrupted = True
                self._stop_machine()
            elif kind == "error":
                print(f"ventana: {event.get('message')}", file=sys.stderr)
            elif kind == "closed":
                self.closed = True
                device.disconnect_keyboard()
                device.disconnect_mouse()
                self._stop_machine()

    def _stop_machine(self) -> None:
        machine = self.machine
        if machine is None:
            return
        if hasattr(machine, "peripheral_halted"):
            machine.peripheral_halted = True        # GPU
        else:
            machine.halted = True                   # CPU

    def _title(self) -> str:
        count = getattr(self.machine, "instructions_executed", None)
        return f"{count} instrucciones" if count is not None else ""

    def _send_screen(self, force: bool = False) -> None:
        now = time.monotonic()
        if self.process is None or self.machine is None:
            return
        if not force and now - self._last_send < self.period:
            return
        self._last_send = now
        snap = screen.snapshot(self.machine)
        if snap == self._last_snapshot and not force:
            if now - self._last_title >= 0.5:       # solo el título
                self._last_title = now
                self._write({"title": self._title()})
            return
        self._last_snapshot = snap
        payload = dict(snap)
        if payload["fb"] is not None:
            payload["fb"] = base64.b64encode(payload["fb"]).decode("ascii")
        self._write({"screen": payload, "title": self._title()})

    def _write(self, message: dict) -> None:
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, AttributeError, ValueError):
            self.closed = True

    def finish(self, device) -> None:
        """El programa ha acabado: deja la última imagen hasta que se cierre."""
        try:
            if not self.closed:
                self._send_screen(force=True)
            while not self.closed and not self.interrupted:
                self.apply_events(device)
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self.close()
