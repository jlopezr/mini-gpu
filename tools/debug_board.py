"""El mismo depurador, contra la placa, por el monitor serie.

`BoardTarget` es la otra implementación de `DebugTarget`, y existe para que
`mini-dbg --board` sea literalmente el mismo programa que `mini-dbg
programa.asm`: mismo núcleo, mismos comandos, misma interfaz. Lo único que
cambia es de dónde salen los registros.

La conexión se monta con lo que ya hay --`run_board.load_monitor` para el
`monitor.py` del prototipo y `backends.board` para abrir el puerto--, no con
una copia local: cada prototipo declara su `MonitorClient` con sus regiones de
memoria, y ese es el cliente que se usa.

Lo que la placa NO deja hacer hoy es escribir registros ni mover el PC: eso
pide comandos nuevos en `monitor.v` (punto 11 del TODO). No se finge: la
capacidad no se declara y el comando responde que el objetivo no la soporta.
"""
from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "x.tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "x.tests"))

from tools.debug_target import (  # noqa: E402
    CAPS_FREE_RUN, CAPS_RESET, CAPS_WRITE_MEMORY,
    DebugTarget, TargetError, TargetState, VideoLayout,
)
from tools.mmio_map import (  # noqa: E402
    MMIO_DEV_VIDEO_BIT, MMIO_MAGIC_VALUE, MMIO_SYSTEM_BASE,
    MMIO_SYSTEM_DEVICES_OFF, MMIO_SYSTEM_MAGIC_OFF,
    MMIO_VIDEO_BASE, MMIO_VIDEO_FB_BACK_OFF, MMIO_VIDEO_FB_FRONT_OFF,
)

# Cuánto se espera a que un `run` libre termine antes de rendirse y avisar.
FREE_RUN_TIMEOUT = None

# Las bases de vídeo se preguntan por MMIO v2 y no se cablean, porque el swap
# las intercambia. No hay camino para el mapa v1 (vídeo en 0x80000000, sin
# `VIDEO_CTRL` delante) a propósito: no queda ningún prototipo ahí. Los cinco
# con vídeo --16, 18, 19, 21 y 22-- declaran la ventana en 0x8020_0000, donde
# v2 la puso, y 0x80000000 es hoy SYSTEM. Adivinar una v1 que nadie tiene sería
# leer el magic de SYS_ID creyendo que es una dirección de framebuffer.


class BoardTarget(DebugTarget):
    """Un núcleo real parado en el monitor."""

    capabilities = frozenset({CAPS_WRITE_MEMORY, CAPS_RESET, CAPS_FREE_RUN})
    # 150 KiB por framebuffer son ~1,5 s a 1 Mbaud (medido en
    # `tools/capture-frames`): se puede mirar, pero no refrescar solo.
    fast_memory = False

    def __init__(self, client, name: str = "placa",
                 free_run_timeout: float | None = FREE_RUN_TIMEOUT) -> None:
        self.client = client
        self.name = name
        self.free_run_timeout = free_run_timeout
        self._interrupt = threading.Event()

    def state(self) -> TargetState:
        status = self._call(self.client.get_status)
        return TargetState(
            pc=status.pc,
            halted=status.halted,
            error=status.error,
            error_code=status.error_code,
            # El contador vive en MMIO y sólo lo tienen los prototipos con el
            # dispositivo de rendimiento; sin él, cero, que es lo que se sabe.
            error_pc=status.pc,
            instructions=self._instructions(),
        )

    def _instructions(self) -> int:
        getter = getattr(self.client, "get_instructions", None)
        if getter is None:
            return 0
        try:
            return getter()
        except Exception:
            return 0

    def registers(self) -> list[int]:
        return [self._call(self.client.read_register, index)
                for index in range(32)]

    def read_memory(self, address: int, length: int) -> bytes:
        return self._call(self.client.read_memory, address, length)

    def step(self) -> None:
        # Sin comprobar antes si está parada: el núcleo ya mira su propio
        # estado y cada comprobación de más es una ida y vuelta por el serie.
        self._call(self.client.step_cpu)

    def write_word(self, address: int, value: int) -> None:
        self._call(self.client.write_word, address, value & 0xFFFFFFFF)

    def reset(self) -> None:
        self._call(self.client.reset_cpu)

    def free_run(self, on_progress: Callable[[], None] | None = None) -> None:
        self._interrupt.clear()
        self._call(self.client.run_cpu)
        deadline = (None if self.free_run_timeout is None else
                    time.monotonic() + self.free_run_timeout)
        while not self._call(self.client.get_status).halted:
            if on_progress is not None:
                on_progress()
            if self._interrupt.is_set():
                self._call(self.client.halt_cpu)
                return
            if deadline is not None and time.monotonic() > deadline:
                # Pararla deja la sesión utilizable: el PC queda donde estaba
                # y se puede seguir mirando, que es justo lo que se quiere
                # cuando un programa no termina.
                self._call(self.client.halt_cpu)
                raise TargetError(
                    f"el nucleo sigue corriendo tras {self.free_run_timeout:g}s"
                    "; lo he parado donde estaba")

    def request_interrupt(self) -> None:
        self._interrupt.set()

    def video_layout(self) -> VideoLayout | None:
        """Descubre la ventana de vídeo preguntándole al hardware.

        El magic de SYS_ID primero, porque sin él no se sabe qué mapa hay
        delante y leer direcciones a ciegas devolvería basura con pinta de
        framebuffer. Con él, `DEVICES` dice si esta placa tiene vídeo siquiera.
        Las bases se releen en cada refresco: el swap las intercambia.
        """
        if self._maybe_word(
                MMIO_SYSTEM_BASE + MMIO_SYSTEM_MAGIC_OFF) != MMIO_MAGIC_VALUE:
            return None
        devices = self._maybe_word(MMIO_SYSTEM_BASE + MMIO_SYSTEM_DEVICES_OFF)
        if devices is None or not devices & (1 << MMIO_DEV_VIDEO_BIT):
            return None

        front = self._maybe_word(MMIO_VIDEO_BASE + MMIO_VIDEO_FB_FRONT_OFF)
        back = self._maybe_word(MMIO_VIDEO_BASE + MMIO_VIDEO_FB_BACK_OFF)
        if front is None or back is None:
            return None
        return VideoLayout(front, back)

    def _maybe_word(self, address: int) -> int | None:
        """Una palabra de MMIO, o `None` si esa ventana no existe aquí.

        Preguntar por un registro que no está no es un error del depurador: es
        la respuesta a «¿tiene vídeo esta placa?».
        """
        try:
            return self.client.read_word(address)
        except Exception:
            return None

    @staticmethod
    def _call(function, *args):
        """Un fallo del enlace serie es un error de usuario, no un traceback."""
        try:
            return function(*args)
        except Exception as exc:
            raise TargetError(f"{type(exc).__name__}: {exc}") from None


def connect(prototype: str, port: str | None = None,
            serial_timeout: float = 2.0) -> tuple[BoardTarget, object]:
    """Abre el puerto y devuelve el objetivo y la conexión (para cerrarla)."""
    from backends import board
    from tools.prototype import PrototypeResolutionError
    from tools.run_board import resolve_target

    try:
        # Resuelve la carpeta y carga su `monitor.py`, que es quien trae el
        # `MonitorClient` con las regiones de memoria de ESE prototipo.
        target = resolve_target(prototype)
    except PrototypeResolutionError as exc:
        raise TargetError(str(exc)) from None
    monitor = target.monitor
    port = port or board.detect_port()

    connection = board._open(monitor, port, serial_timeout)
    client = monitor.MonitorClient(connection)
    # Parar antes de mirar nada: leer registros de un núcleo corriendo
    # devuelve valores de instantes distintos, que es peor que no leerlos.
    try:
        if not client.get_status().halted:
            client.halt_cpu()
    except Exception as exc:
        connection.close()
        raise TargetError(
            f"la placa en {port} no responde al monitor: {exc}") from None

    return BoardTarget(client, f"{target.prototype_dir.name} @ {port}"), connection
