"""La ventana de framebuffer del depurador, vista desde el depurador.

Lee los dos buffers del objetivo y se los pasa a `tools/fb_window.py`, que
corre aparte. Aquí no hay nada de Tk: este módulo sólo sabe leer memoria,
escribir un `.bin` temporal y mandar una línea por la tubería.

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

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.debug_target import DebugTarget, TargetError

ROOT = Path(__file__).resolve().parents[1]
BUFFERS = ("front", "back")


class VideoViewer:
    """Un proceso de ventana, o ninguno, y lo que hay que mandarle."""

    def __init__(self, target: DebugTarget) -> None:
        self.target = target
        self.process: subprocess.Popen | None = None
        self.showing: tuple[str, ...] = ()
        # En placa, refrescar cuesta segundos: sólo cuando se pide.
        self.auto = target.fast_memory
        self._directory: tempfile.TemporaryDirectory | None = None

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
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        return "ventana cerrada"

    def refresh(self, force: bool = False) -> None:
        """Vuelve a leer y mandar. Sin `force`, respeta el modo automático.

        Que la ventana esté cerrada no es un fallo: el depurador la llama
        después de cada comando y lo normal es no tenerla abierta.
        """
        if not self.showing:
            return
        if not self.open:
            # La ha cerrado quien depura, con la X o con Escape.
            self.process = None
            self.showing = ()
            return
        if not (force or self.auto):
            return

        layout = self.layout()
        payload: dict[str, object] = {"title": self._title()}
        for name in self.showing:
            address = layout.fb_front if name == "front" else layout.fb_back
            path = self._write(name, address, layout.frame_bytes)
            payload[name] = str(path)
        for name in BUFFERS:
            if name not in self.showing:
                payload[name] = None

        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            self.process = None
            self.showing = ()

    def _title(self) -> str:
        state = self.target.state()
        return (f"{self.target.name}  PC=0x{state.pc:08X}  "
                f"instr={state.instructions}")

    def _write(self, name: str, address: int, size: int) -> Path:
        try:
            data = self.target.read_memory(address, size)
        except TargetError as exc:
            raise TargetError(
                f"framebuffer {name} en 0x{address:08X}: {exc}") from None
        if self._directory is None:
            self._directory = tempfile.TemporaryDirectory(prefix="mini-dbg-")
        # Se escribe a fichero y no por la tubería porque son 150 KiB por
        # refresco: por stdin habría que trocear y sincronizar, y el fichero
        # temporal lo resuelve sin inventar un protocolo binario.
        path = Path(self._directory.name) / f"{name}.bin"
        path.write_bytes(data)
        return path

    def _spawn(self) -> None:
        layout = self.layout()
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(ROOT / "tools" / "fb_window.py"),
                 f"{layout.width}x{layout.height}"],
                stdin=subprocess.PIPE, text=True)
        except OSError as exc:
            raise TargetError(f"no se pudo abrir la ventana: {exc}") from None
