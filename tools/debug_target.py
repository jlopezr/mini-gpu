"""Qué necesita un depurador de la máquina que depura, y nada más.

`DebugTarget` es la frontera entre el depurador y lo que ejecuta: registros,
memoria, un paso, y el estado de parada. Está escrita mirando de reojo a
`monitor_protocol.MonitorClient` --`step_cpu`, `read_register`, `read_memory`,
`write_word`, `get_status`-- porque el objetivo declarado es que la placa entre
después como un `BoardTarget` sin tocar ni el núcleo ni la interfaz.

De ahí las `CAPS_*`: no todo objetivo sabe hacer todo. El simulador puede
escribir cualquier registro y mover el PC; la placa, hoy, no --restaurar estado
arquitectónico desde fuera pide comandos nuevos en `monitor.v`, que es justo el
punto 11 del TODO--. En vez de fingir que sí y fallar en tiempo de ejecución,
cada objetivo declara lo que soporta y el núcleo rechaza el comando con un
motivo legible.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

# Qué sabe hacer un objetivo, más allá del mínimo (leer estado y dar un paso).
CAPS_WRITE_REGISTER = "write-register"
CAPS_WRITE_PC = "write-pc"
CAPS_WRITE_MEMORY = "write-memory"
CAPS_RESET = "reset"
#: El objetivo sabe correr solo hasta pararse, sin ir instrucción a instrucción.
#: Lo tiene la placa (`RUN` del monitor) y no el simulador, que ya es rápido
#: dando pasos. Sin esto, un `run` sin breakpoints en la placa serían miles de
#: `STEP` por el puerto serie, a 115200 baudios.
CAPS_FREE_RUN = "free-run"


@dataclass(frozen=True)
class VideoLayout:
    """Dónde están los dos framebuffers de ESTE objetivo, ahora mismo.

    No es una constante: `FB_FRONT` y `FB_BACK` los escribe el programa y se
    intercambian en cada swap, así que se vuelven a leer en cada refresco. El
    tamaño va aquí porque quien lo sepa es el objetivo, no la ventana.
    """

    fb_front: int
    fb_back: int
    width: int = 320
    height: int = 240

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * 2


@dataclass(frozen=True)
class TargetState:
    """Foto del estado de parada, equivalente a `CpuStatus` del monitor."""

    pc: int
    halted: bool
    error: bool
    error_code: int
    error_pc: int
    instructions: int


class TargetError(RuntimeError):
    """Lo que el objetivo no puede hacer, dicho para que lo lea una persona."""


class DebugTarget(ABC):
    """Una máquina que se puede parar, mirar y hacer avanzar de una en una."""

    #: Nombre corto para la barra de estado ("simulador", "placa COM3"...).
    name: str = "objetivo"
    #: Subconjunto de las constantes CAPS_* que este objetivo soporta.
    capabilities: frozenset[str] = frozenset()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def require(self, capability: str) -> None:
        """Lanza `TargetError` si el objetivo no soporta la capacidad."""
        if not self.supports(capability):
            raise TargetError(
                f"{self.name} no soporta '{capability}'"
            )

    @abstractmethod
    def state(self) -> TargetState:
        ...

    @abstractmethod
    def registers(self) -> list[int]:
        """Los 32 registros enteros, R0 incluido."""

    @abstractmethod
    def read_memory(self, address: int, length: int) -> bytes:
        """Lee `length` bytes. Lanza `TargetError` si la región no es legible."""

    @abstractmethod
    def step(self) -> None:
        """Ejecuta una instrucción. Con la máquina parada, no hace nada."""

    def set_register(self, index: int, value: int) -> None:
        self.require(CAPS_WRITE_REGISTER)
        raise NotImplementedError

    def set_pc(self, value: int) -> None:
        self.require(CAPS_WRITE_PC)
        raise NotImplementedError

    def write_word(self, address: int, value: int) -> None:
        self.require(CAPS_WRITE_MEMORY)
        raise NotImplementedError

    def reset(self) -> None:
        self.require(CAPS_RESET)
        raise NotImplementedError

    def free_run(self, on_progress: Callable[[], None] | None = None) -> None:
        """Arranca y espera a que la máquina se pare por su cuenta."""
        self.require(CAPS_FREE_RUN)
        raise NotImplementedError

    def request_interrupt(self) -> None:
        """Solicita parar una ejecución larga, si el objetivo corre solo."""

    def video_layout(self) -> VideoLayout | None:
        """Dónde mirar el framebuffer, o `None` si esta máquina no tiene vídeo.

        Lo resuelve cada objetivo porque cada uno lo sabe de una forma: el
        simulador tiene el dispositivo delante y la placa tiene que preguntar
        por MMIO, donde además las direcciones cambiaron entre v1 y v2.
        """
        return None

    def video_swap_count(self) -> int | None:
        """Intercambios completados, o `None` si no se pueden observar."""
        return None

    #: Si leer 150 KiB es instantáneo. En la placa son ~1,5 s por framebuffer a
    #: 1 Mbaud, y de eso depende que la ventana se refresque sola o a mano.
    fast_memory: bool = True


class SimTarget(DebugTarget):
    """El simulador funcional de MiniCPU (`2.cpu-sim-func/minicpu_sim.py`).

    Es una envoltura fina a propósito: no guarda estado propio, todo lo lee del
    objeto `CPU`. Así el depurador nunca puede mostrar una copia desfasada, y
    quien tenga la CPU por otro lado (un test, por ejemplo) la ve cambiar.
    """

    name = "simulador"
    capabilities = frozenset({
        CAPS_WRITE_REGISTER, CAPS_WRITE_PC, CAPS_WRITE_MEMORY, CAPS_RESET,
    })

    def __init__(self, cpu) -> None:
        self.cpu = cpu

    def state(self) -> TargetState:
        cpu = self.cpu
        return TargetState(
            pc=cpu.pc,
            halted=cpu.halted,
            error=cpu.error,
            error_code=cpu.error_code,
            error_pc=cpu.error_pc,
            instructions=cpu.instructions_executed,
        )

    def registers(self) -> list[int]:
        return list(self.cpu.regs)

    def read_memory(self, address: int, length: int) -> bytes:
        memory = self.cpu.memory
        if address < 0 or length < 0 or address + length > len(memory):
            raise TargetError(
                f"fuera de memoria: 0x{address:08X}+{length}"
            )
        # Directo sobre el bytearray, no por `read_u32`: mirar memoria no debe
        # tener efectos secundarios, y en MMIO una lectura los tiene (el serie
        # consume el byte que se lee). Un panel que refresca cada paso no puede
        # ir vaciando la FIFO del programa que se está depurando.
        return bytes(memory[address:address + length])

    def step(self) -> None:
        self.cpu.step()

    def set_register(self, index: int, value: int) -> None:
        if not 0 <= index < len(self.cpu.regs):
            raise TargetError(f"registro fuera de rango: R{index}")
        if index == 0:
            raise TargetError("R0 está cableado a cero")
        self.cpu.set_register(index, value & 0xFFFFFFFF)

    def set_pc(self, value: int) -> None:
        if value & 3:
            raise TargetError(f"PC no alineado: 0x{value:08X}")
        self.cpu.pc = value & 0xFFFFFFFF

    def write_word(self, address: int, value: int) -> None:
        try:
            self.cpu.write_u32(address, value & 0xFFFFFFFF)
        except RuntimeError as exc:
            raise TargetError(str(exc)) from None

    def reset(self) -> None:
        # `reset()` del simulador no borra la memoria, así que reinicia el
        # programa ya cargado: es lo que se espera de un `reset` de depurador.
        self.cpu.reset()

    def video_layout(self) -> VideoLayout | None:
        # El dispositivo está aquí al lado, así que no hay que adivinar nada
        # por MMIO: se le preguntan las bases, que es donde vive la verdad.
        # Sin `--video` no hay dispositivo y no hay nada que enseñar.
        video = getattr(self.cpu, "video", None)
        if video is None:
            return None
        return VideoLayout(video.fb_front, video.fb_back)

    def video_swap_count(self) -> int | None:
        video = getattr(self.cpu, "video", None)
        return None if video is None else video.swap_count
