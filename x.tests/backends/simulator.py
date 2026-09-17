"""Backend del simulador funcional para los tests comunes de CPU."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from . import video_layout
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.sim_peripherals import video_result


VERSIONS = {
    "current": {
        "simulator_path": Path("2.cpu-sim-func/minicpu_sim.py"),
        "memory_size": 32 * 1024 * 1024,
        # El simulador va siempre por delante del RTL: implementa la ISA
        # entera, incluidas las extensiones que solo tiene el bitstream de la
        # 19. Ver el comentario de CAPABILITIES en run_tests.py.
        # `mul_div` llega implicada por `alu_extended`, pero se declara aparte
        # igualmente: aqui no es una extension sino la base de la ISA, y el
        # simulador la tiene desde siempre.
        "capabilities": ("frame_capture", "subword_memory", "calls", "serial",
                         "shift_immediate", "alu_extended", "mul_div",
                         "compare"),
        "description": "simulador funcional MiniCPU actual",
    },
}
DEFAULT_VERSION = "current"



def expand_for(names) -> frozenset:
    """Expande las capacidades implicadas.

    El import va dentro para no crear una dependencia circular: `run_tests`
    importa los backends al arrancar.
    """
    from run_tests import expand_capabilities

    return expand_capabilities(names)


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene este simulador, con las implicaciones ya expandidas."""
    return expand_for(VERSIONS[version]["capabilities"])


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Qué casos no caben aquí.

    El simulador tiene la ventana de registros de vídeo y un reloj de frames
    sintético, así que acepta `video` y `frame_capture`. Lo que sigue sin tener
    es TIEMPO: no hay barrido leyendo la memoria por su cuenta, ni ancho de
    banda, ni contienda. `VideoDevice` en `minicpu_sim.py` lo explica entero; el
    resumen es que aquí se valida QUÉ dibuja un programa, nunca CUÁNDO.

    En concreto, `underflow` es siempre cero y no puede ser otra cosa: una
    expectativa `underflow: false` pasa aquí sin comprobar nada. Sigue mereciendo
    la pena tenerla en el caso, porque en hardware sí significa algo, pero
    conviene no confundir un verde de aquí con haber probado eso.

    La comprobación se hace igual que en la FPGA aunque hoy el simulador tenga
    todas las capacidades declaradas: el día que se añada una capacidad nueva a
    la ISA, el simulador la tendrá antes que el RTL y un `requires` sin
    respaldo tiene que dar SKIP, no un error de opcode inválido a medio caso.
    """
    disponibles = capabilities(version)
    faltan = [name for name in case.get("requires", []) if name not in disponibles]
    if faltan:
        return f"el simulador {version!r} no tiene {', '.join(faltan)}"
    return None


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SimulatorBackend:
    """Ejecuta un caso sobre ``2.cpu-sim-func/minicpu_sim.py``."""

    ARCHITECTURE = "cpu"

    def __init__(
        self,
        repository: Path,
        version: str = DEFAULT_VERSION,
        memory_size: int | None = None,
    ):
        try:
            configuration = VERSIONS[version]
        except KeyError as error:
            choices = ", ".join(sorted(VERSIONS))
            raise ValueError(
                f"Versión del simulador desconocida {version!r}; opciones: {choices}"
            ) from error

        self.version = version
        module = _load_module(
            f"minicpu_sim_{version}_for_tests",
            repository / configuration["simulator_path"],
        )
        self.cpu_class = module.CPU
        self.video_class = getattr(module, "VideoDevice", None)
        self.serial_class = getattr(module, "SerialDevice", None)
        self.memory_size = memory_size or configuration["memory_size"]

    def run(
        self,
        program: bytes,
        initial_memory: list[tuple[int, bytes]],
        register_numbers: set[int],
        memory_ranges: list[tuple[int, int]],
        max_instructions: int,
        timeout_seconds: float,
        video: dict | None = None,
        stdin: bytes = b"",
    ) -> dict:
        del timeout_seconds  # El simulador usa un límite de instrucciones.

        dispositivo = None
        if video is not None:
            if self.video_class is None:
                raise RuntimeError(
                    f"el simulador {self.version!r} no tiene VideoDevice")
            dispositivo = self.video_class()
            # Poner el framebuffer donde el arnés lo quiere, igual que hace el
            # backend de placa. El dispositivo arranca con las bases a cero
            # --como el hardware-- y hay casos que dibujan donde les digan.
            # Ver backends/video_layout.py.
            dispositivo.write(dispositivo.FB_FRONT, video_layout.FB_FRONT)
            dispositivo.write(dispositivo.FB_BACK, video_layout.FB_BACK)
            swap = video.get("run_until_swap")
            if swap:
                # Por `write`, no asignando el atributo: armar la alarma tiene
                # efectos —pone SWAP_COUNT a cero y levanta el bit de armado—
                # igual que en el hardware. Asignando `halt_at` a pelo se
                # queda desarmada y el programa no para nunca.
                dispositivo.write(dispositivo.HALT_AT, swap)

        # El puerto serie se construye SIEMPRE que el caso lo pida, aunque
        # `stdin` este vacio: un programa puede escribir sin haber leido nada.
        serie = None
        if stdin or self.serial_class is not None:
            if self.serial_class is None:
                raise RuntimeError(
                    f"el simulador {self.version!r} no tiene SerialDevice")
            serie = self.serial_class(stdin=stdin)
            serie.attach_host()

        cpu = self.cpu_class(self.memory_size, video=dispositivo, serial=serie)
        cpu.load_program(program)

        for address, data in initial_memory:
            end = address + len(data)
            if address < 0 or end > len(cpu.memory):
                raise ValueError(f"Inicialización fuera de memoria: 0x{address:08x}")
            cpu.memory[address:end] = data

        cpu.run(max_instructions)

        resultado_video = video_result(cpu, bool(video and video.get("capture_frame")))
        return {
            # El simulador cuenta instrucciones pero no ciclos: no modela el
            # tiempo, asi que `cycles` es None a proposito y el CPI de una fila
            # de simulador no existe. Lo que si aporta es el numero de
            # instrucciones, que es arquitectonico y por tanto sirve de
            # contraste contra el contador de la placa.
            "cycles": None,
            "instructions": cpu.instructions_executed,
            "clock_hz": None,
            "halted": cpu.halted,
            "error": cpu.error,
            "error_code": cpu.error_code,
            "pc": cpu.pc,
            "registers": {number: cpu.regs[number] for number in register_numbers},
            "memory": {
                (address, size): bytes(cpu.memory[address:address + size])
                for address, size in memory_ranges
            },
            "video": resultado_video,
            # Lo que el programa dejo en la cola de salida. Es el campo que el
            # diferencial puede comparar contra la placa byte a byte: a
            # diferencia del video, un flujo de bytes no depende del tiempo.
            "stdout": serie.output() if serie is not None else None,
        }
