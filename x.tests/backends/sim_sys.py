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

from pathlib import Path

from .sim_common import capabilities_of, missing_capabilities
from .sim_cpu import SimCpuBackend


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
    return capabilities_of(VERSIONS, version)


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Qué casos no caben aquí: los que piden algo que el simulador no declara."""
    faltan = missing_capabilities(case, capabilities(version))
    if faltan:
        return f"el simulador {version!r} no tiene {', '.join(faltan)}"
    return None


class SimSysBackend(SimCpuBackend):
    """Ejecuta un caso de CPU sobre ``32.cpu-gpu-func-sim/cpu_gpu_sim.py``.

    Todo es el de `SimCpuBackend` salvo la máquina: un `CpuGpuSystem` en vez de
    una CPU sola. Los registros, el PC y el contador de instrucciones son los de
    su CPU, que es lo que `fpga-cpu` observa en la 36 y la 37.
    """

    VERSIONS = VERSIONS
    MODULE_PREFIX = "cpu_gpu_sim"

    def __init__(self, repository: Path, version: str = DEFAULT_VERSION,
                 memory_size: int | None = None):
        super().__init__(repository, version, memory_size)
        # `cpu_gpu_sim.py` no define los periféricos: usa los de `tools`.
        from tools import sim_devices
        self.devices = sim_devices

    def _build(self, video, serial, input_dev):
        system = self.module.CpuGpuSystem(
            self.memory_size, video=video, serial=serial, input_device=input_dev)
        return system, system.cpu
