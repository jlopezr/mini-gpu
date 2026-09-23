"""La ventana de framebuffer del depurador, vista desde el depurador.

Lee los dos buffers del objetivo y se los pasa a `tools/fb_window.py`, que
corre aparte. Aquí no hay nada de Tk: este módulo sólo sabe leer memoria y
mandar una línea JSON con los píxeles codificados en Base64 por la tubería.
La ventana devuelve por stdout los eventos que pertenecen al depurador, como
`Esc` para interrumpir la ejecución sin cerrar el framebuffer.

El coste de refrescar no es el mismo en los dos sitios, y eso decide el
comportamiento por defecto. En el simulador leer un framebuffer es copiar 150
KiB de un `bytearray`, así que la ventana se refresca sola después de cada
comando y se ve el programa dibujar paso a paso. En la placa son ~1,5 s por
buffer a 1 Mbaud, así que se refresca cuando se pide. `fb auto` fuerza lo uno
o lo otro si en algún caso concreto interesa lo contrario.

Front y back no enseñan lo mismo, a propósito. El front es el frame estable,
el que está saliendo por HDMI. El back es sobre el que el programa está
dibujando ahora, así que con la CPU parada a mitad de dibujo sale a medias —
que es exactamente lo que se quiere ver cuando se busca dónde se atasca. Es lo
contrario de lo que hace `tools/capture-frames`, que para en el swap
precisamente para que la captura sea entera y determinista.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from tools.debug_target import DebugTarget, TargetError

ROOT = Path(__file__).resolve().parents[1]
BUFFERS = ("front", "back")


class VideoViewer:
    """Un proceso de ventana, o ninguno, y lo que hay que mandarle."""

    def __init__(self, target: DebugTarget,
                 on_interrupt: Callable[[], None] | None = None,
                 on_key: Callable[[str], None] | None = None,
                 on_error: Callable[[str], None] | None = None) -> None:
        self.target = target
        self.on_interrupt = on_interrupt
        self.on_key = on_key
        self.on_error = on_error
        self.process: subprocess.Popen | None = None
        self.showing: tuple[str, ...] = ()
        # En placa, refrescar cuesta segundos: sólo cuando se pide.
        self.auto = target.fast_memory
        self._last_title_refresh = 0.0

    @property
    def open(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def layout(self):
        layout = self.target.video_layout()
        if layout is None:
            raise TargetError(
                f"{self.target.name} no tiene video "
                "(en el simulador hace falta --video)")
        return layout

    def show(self, buffers: tuple[str, ...]) -> str:
        """Abre la ventana si hace falta y pinta los buffers pedidos."""
        for name in buffers:
            if name not in BUFFERS:
                raise TargetError(f"no existe el buffer '{name}'")
        self.layout()  # falla pronto y con motivo si no hay vídeo
        self.showing = buffers
        if not self.open:
            self._spawn()
        self.refresh(force=True)
        return f"ventana: {' + '.join(buffers)}"

    def close(self) -> str:
        if self.open:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        self.showing = ()
        return "ventana cerrada"

    def refresh(self, force: bool = False) -> None:
        """Vuelve a leer y mandar. Sin `force`, respeta el modo automático.

        Que la ventana esté cerrada no es un fallo: el depurador la llama
        después de cada comando y lo normal es no tenerla abierta.
        """
        if not self.showing:
            return
        if not self.open:
            # La ha cerrado quien depura con la X.
            self.process = None
            self.showing = ()
            return
        if not (force or self.auto):
            return

        layout = self.layout()
        payload: dict[str, object] = {"title": self._title()}
        for name in self.showing:
            address = layout.fb_front if name == "front" else layout.fb_back
            payload[name] = self._read_base64(name, address,
                                              layout.frame_bytes)
        for name in BUFFERS:
            if name not in self.showing:
                payload[name] = None

        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            self.process = None
            self.showing = ()

    def refresh_title(self, force: bool = False) -> None:
        """Actualiza solo PC/contador, sin volver a leer ningún framebuffer."""
        if not self.open:
            return
        now = time.monotonic()
        if not force and now - self._last_title_refresh < 0.1:
            return
        self._last_title_refresh = now
        try:
            self.process.stdin.write(json.dumps({"title": self._title()}) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            self.process = None
            self.showing = ()

    def _title(self) -> str:
        state = self.target.state()
        return (f"{self.target.name}  PC=0x{state.pc:08X}  "
                f"instr={state.instructions}")

    def _read_base64(self, name: str, address: int, size: int) -> str:
        try:
            data = self.target.read_memory(address, size)
        except TargetError as exc:
            raise TargetError(
                f"framebuffer {name} en 0x{address:08X}: {exc}") from None
        return base64.b64encode(data).decode("ascii")

    def _spawn(self) -> None:
        layout = self.layout()
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(ROOT / "tools" / "fb_window.py"),
                 f"{layout.width}x{layout.height}"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            threading.Thread(
                target=self._read_events, args=(self.process,), daemon=True
            ).start()
        except OSError as exc:
            raise TargetError(f"no se pudo abrir la ventana: {exc}") from None

    def _read_events(self, process: subprocess.Popen) -> None:
        """Recibe eventos de Tk sin bloquear el hilo de la TUI."""
        if process.stdout is None:
            return
        for line in process.stdout:
            self._handle_event(line)

    def _handle_event(self, line: str) -> None:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            if self.on_error is not None and line.strip():
                self.on_error(line.strip())
            return
        if event.get("event") == "interrupt" and self.on_interrupt is not None:
            self.on_interrupt()
        elif event.get("event") == "key" and self.on_key is not None:
            key = event.get("key")
            if isinstance(key, str):
                self.on_key(key)
        elif event.get("event") == "error" and self.on_error is not None:
            message = event.get("message")
            if isinstance(message, str):
                self.on_error(message)
