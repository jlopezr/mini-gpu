"""Backend del simulador funcional para los tests comunes de CPU."""

from __future__ import annotations

from pathlib import Path

from .sim_common import (
    capabilities_of, input_device, load_initial_memory, load_module,
    make_serial, make_video, missing_capabilities, video_result,
)


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
                         "compare", "large_memory", "input"),
        "description": "simulador funcional MiniCPU actual",
    },
}
DEFAULT_VERSION = "current"


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene este simulador, con las implicaciones ya expandidas."""
    return capabilities_of(VERSIONS, version)


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
    missing = missing_capabilities(case, capabilities(version))
    if missing:
        return f"el simulador {version!r} no tiene {', '.join(missing)}"
    return None


class SimCpuBackend:
    """Ejecuta un caso sobre ``2.cpu-sim-func/minicpu_sim.py``."""

    ARCHITECTURE = "cpu"
    VERSIONS = VERSIONS

    def __init__(
        self,
        repository: Path,
        version: str = DEFAULT_VERSION,
        memory_size: int | None = None,
    ):
        try:
            configuration = self.VERSIONS[version]
        except KeyError as error:
            choices = ", ".join(sorted(self.VERSIONS))
            raise ValueError(
                f"Versión del simulador desconocida {version!r}; opciones: {choices}"
            ) from error

        self.version = version
        self.module = load_module(
            f"{self.MODULE_PREFIX}_{version}_for_tests",
            repository / configuration["simulator_path"],
        )
        self.memory_size = memory_size or configuration["memory_size"]
        # Dónde están `VideoDevice` y `SerialDevice`: en el propio simulador.
        self.devices = self.module

    MODULE_PREFIX = "minicpu_sim"

    def _build(self, video, serial, input_dev):
        """La máquina y su CPU. Aquí son lo mismo; `sim_sys` añade la GPU."""
        cpu = self.module.CPU(self.memory_size, video=video, serial=serial,
                              input_device=input_dev)
        return cpu, cpu

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
        input_script: str | None = None,
    ) -> dict:
        del timeout_seconds  # El simulador usa un límite de instrucciones.

        what = f"el simulador {self.version!r}"
        device = make_video(self.devices, video, what)
        serial_device = make_serial(self.devices, stdin, what)
        machine, cpu = self._build(device, serial_device, input_device(input_script))
        cpu.load_program(program)
        load_initial_memory(machine.memory, initial_memory)

        machine.run(max_instructions)

        video_info = video_result(machine, bool(video and video.get("capture_frame")))
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
                (address, size): bytes(machine.memory[address:address + size])
                for address, size in memory_ranges
            },
            "video": video_info,
            # Lo que el programa dejo en la cola de salida. Es el campo que el
            # diferencial puede comparar contra la placa byte a byte: a
            # diferencia del video, un flujo de bytes no depende del tiempo.
            "stdout": serial_device.output() if serial_device is not None else None,
        }
