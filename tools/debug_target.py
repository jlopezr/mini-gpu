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
#: El objetivo es una GPU con su propio reset (sin tocar descriptores ni memoria)
#: además del reset del sistema entero.
CAPS_RESET_GPU = "reset-gpu"

# Qué contesta `DebugTarget.poll` cuando hay que parar. Son las mismas cadenas
# que los `STOP_*` del núcleo, que los reexporta.
POLL_BREAKPOINT = "breakpoint"
POLL_HALT = "halt"
POLL_ERROR = "error"
POLL_STALLED = "stalled"


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


@dataclass(frozen=True)
class WarpRow:
    """Una fila de la tabla de warps de una GPU."""

    number: int
    #: LIBRE, READY, WAIT_BAR, FIN (terminó y nadie lo ha recogido) o ERROR.
    state: str
    pc: int
    active_mask: int
    live_mask: int
    region_depth: int
    path_depth: int
    logical_id: int
    arg: int
    #: El warp con el foco de depuración.
    focused: bool
    #: Un `step` suyo avanzaría (vivo y no bloqueado).
    runnable: bool
    #: Lanes por warp, para pintar las máscaras.
    lanes: int = 8


@dataclass(frozen=True)
class LaneGrid:
    """Los registros de todas las lanes de un warp: `regs[lane][registro]`."""

    warp: int
    lane: int
    active_mask: int
    live_mask: int
    regs: tuple[tuple[int, ...], ...]


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

    # -- ejecución libre ----------------------------------------------------
    # `run`, `until` y `frame` no llaman a `step`: repiten `advance` y preguntan
    # a `poll` si toca parar. En un solo núcleo son `step` y «¿PC en una marca?»;
    # un sistema con varios núcleos decide aquí quién avanza y quién ha parado.

    def can_run(self) -> bool:
        """Si ejecutar libremente puede cambiar algo."""
        return not self.state().halted

    #: Lo activa la sesión mientras haya `watch`: pide a `advance` recordar qué
    #: instrucción ejecutó, para poder decir quién escribió. Apagado no cuesta nada.
    track_writer: bool = False
    _writer: str = ""

    def advance(self) -> bool:
        """Una unidad de ejecución libre. False si nada pudo avanzar."""
        if self.track_writer:
            self._writer = f"PC=0x{self.state().pc:08X}"
        self.step()
        return True

    def last_writer(self) -> str:
        """Quién ejecutó la última instrucción de `advance` (`PC=0x...`)."""
        return self._writer

    def focus_last_actor(self) -> None:
        """Pone el foco en el núcleo de la última instrucción de `advance`."""

    def pcs(self) -> tuple[int, int | None] | None:
        """(PC de la CPU, PC del warp con foco si está vivo) para marcar el
        listado con los dos indicadores, o `None` si hay un solo núcleo."""
        return None

    def poll(self, marks: set[int]) -> str | None:
        """Tras `advance`: `POLL_*` si hay que parar, o `None` para seguir.

        Un objetivo con varios núcleos mueve aquí su foco al que ha parado.
        """
        state = self.state()
        if state.halted:
            return POLL_ERROR if state.error else POLL_HALT
        if state.pc in marks:
            return POLL_BREAKPOINT
        return None

    def stop_location(self) -> str:
        """Qué núcleo está parado, para los mensajes (` [GPU w3]`), o vacío."""
        return ""

    def idle_reason(self) -> str | None:
        """Por qué `step` no puede hacer nada, si hay una razón mejor que «parada»."""
        return None

    def pop_notices(self) -> list[str]:
        """Avisos acumulados desde la última vez (cambios de foco automáticos)."""
        return []

    def summary(self) -> str:
        """Texto extra para la barra de estado (el otro núcleo, por ejemplo)."""
        return ""

    # -- varios núcleos -----------------------------------------------------

    def warp_rows(self) -> list[WarpRow] | None:
        """La tabla de warps, o `None` si el objetivo no tiene GPU."""
        return None

    def lane_grid(self) -> LaneGrid | None:
        """Registros de todas las lanes del warp con foco, o `None`."""
        return None

    def focus_key(self) -> tuple | None:
        """Identifica el núcleo con foco: si cambia, no se comparan registros."""
        return None

    def core(self) -> str:
        """`cpu` o `gpu`: el núcleo con foco."""
        return "cpu"

    def set_core(self, core: str | None) -> None:
        raise TargetError(f"{self.name} no tiene GPU")

    def select_warp(self, number: int | None) -> None:
        raise TargetError(f"{self.name} no tiene GPU")

    def select_lane(self, number: int | None) -> None:
        raise TargetError(f"{self.name} no tiene GPU")

    def reset_gpu(self) -> None:
        self.require(CAPS_RESET_GPU)
        raise NotImplementedError

    def gpu_fault(self) -> bool:
        """Si la GPU tiene un error pendiente."""
        return False

    def round_warps(self) -> list[int]:
        """Una instrucción en cada warp que pueda avanzar, en orden de warp.

        Devuelve los warps que ejecutaron. El foco no se mueve.
        """
        raise TargetError(f"{self.name} no tiene GPU")

    def sched_step(self) -> int:
        """Una instrucción del warp que elegiría el planificador; el foco pasa
        a él. Devuelve su número."""
        raise TargetError(f"{self.name} no tiene GPU")

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

    def simulated_machine(self):
        """El simulador que hay detrás, o `None` en la placa. La ventana de
        pantalla y el comando `input` miran su estado directamente."""
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

    def simulated_machine(self):
        return self.cpu
