"""Backend del simulador CPU+GPU (carpeta 32) para los casos de CPU que lanzan la GPU.

Es el `sim-cpu` con una GPU colgada del bus MMIO: la CPU ejecuta el programa y
el kernel de la GPU va en la misma imagen, en RAM compartida. La arquitectura es
`cpu` --el caso lo escribe y lo observa la CPU--, y declara `gpu_core` y
`gpu_warp_start` para que `cases-cpu/gpu/*` corra también sin placa. Su pareja
en hardware es `fpga-cpu` sobre la 36 o la 37.

No es la pareja de `fpga-sys`: ese lanza casos de `cases-gpu/` desde el host, sin
programa de CPU, y su pareja de simulador es `sim-gpu`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.sim_peripherals import video_result

from backends.sim_cpu import _load_module, expand_for, input_device


VERSIONS = {
    "current": {
        "simulator_path": Path("32.cpu-gpu-func-sim/cpu_gpu_sim.py"),
        "memory_size": 32 * 1024 * 1024,
        # Las de `sim-cpu` --la CPU es la misma-- y las dos de GPU CORE.
        "capabilities": ("frame_capture", "subword_memory", "calls", "serial",
                         "shift_immediate", "alu_extended", "mul_div",
                         "compare", "large_memory", "input",
                         "gpu_core", "gpu_warp_start"),
        "description": "simulador funcional MiniCPU + MiniGPU actual",
    },
}
DEFAULT_VERSION = "current"


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene este simulador, con las implicaciones ya expandidas."""
    return expand_for(VERSIONS[version]["capabilities"])


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Qué casos no caben aquí: los que piden algo que el simulador no declara."""
    faltan = [name for name in case.get("requires", [])
              if name not in capabilities(version)]
    if faltan:
        return f"el simulador {version!r} no tiene {', '.join(faltan)}"
    return None


class CpuGpuSimulatorBackend:
    """Ejecuta un caso de CPU sobre ``32.cpu-gpu-func-sim/cpu_gpu_sim.py``."""

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
            f"cpu_gpu_sim_{version}_for_tests",
            repository / configuration["simulator_path"],
        )
        self.system_class = module.CpuGpuSystem
        self.video_class = module.VideoDevice
        from tools.sim_devices import SerialDevice
        self.serial_class = SerialDevice
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
        input_script: str | None = None,
    ) -> dict:
        del timeout_seconds  # El simulador usa un límite de instrucciones.

        dispositivo = None
        if video is not None:
            dispositivo = self.video_class()
            swap = video.get("run_until_swap")
            if swap:
                # Parada del arnés, que detiene CPU y GPU: ver `sim-cpu`.
                dispositivo.stop_after_swaps = swap

        serie = self.serial_class(stdin=stdin)
        serie.attach_host()

        system = self.system_class(
            self.memory_size, video=dispositivo, serial=serie,
            input_device=input_device(input_script))
        system.load_cpu_program(program)

        for address, data in initial_memory:
            end = address + len(data)
            if address < 0 or end > len(system.memory):
                raise ValueError(f"Inicialización fuera de memoria: 0x{address:08x}")
            system.memory[address:end] = data

        system.run(max_instructions)

        cpu = system.cpu
        return {
            "cycles": None,
            "instructions": cpu.instructions_executed,
            "clock_hz": None,
            "halted": cpu.halted,
            "error": cpu.error,
            "error_code": cpu.error_code,
            "pc": cpu.pc,
            "registers": {number: cpu.regs[number] for number in register_numbers},
            "memory": {
                (address, size): bytes(system.memory[address:address + size])
                for address, size in memory_ranges
            },
            "video": video_result(system, bool(video and video.get("capture_frame"))),
            "stdout": serie.output(),
        }
