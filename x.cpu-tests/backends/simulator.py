"""Backend del simulador funcional para los tests comunes de CPU."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


VERSIONS = {
    "current": {
        "simulator_path": Path("2.cpu-sim-func/minicpu_sim.py"),
        "memory_size": 32 * 1024 * 1024,
        "description": "simulador funcional MiniCPU actual",
    },
}
DEFAULT_VERSION = "current"


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """El simulador no tiene vídeo, y no es una carencia que vaya a llenarse.

    Es un simulador de la ISA: no hay barrido, ni framebuffer que nadie lea por
    su cuenta, ni registros en 0x80000000. Un caso que declare `video` o
    `frame_capture` se omite aquí y se ejecuta en la FPGA, que es donde esas
    cosas existen.
    """
    del version
    graficas = [
        name for name in case.get("requires", [])
        if name in ("video", "frame_capture")
    ]
    if graficas:
        return (
            f"el simulador no tiene {', '.join(graficas)}: no hay barrido ni "
            "framebuffer, use --backend cpu-fpga --version bl8"
        )
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
        self.memory_size = memory_size or configuration["memory_size"]

    def run(
        self,
        program: bytes,
        initial_memory: list[tuple[int, bytes]],
        register_numbers: set[int],
        memory_ranges: list[tuple[int, int]],
        max_instructions: int,
        timeout_seconds: float,
    ) -> dict:
        del timeout_seconds  # El simulador usa un límite de instrucciones.

        cpu = self.cpu_class(self.memory_size)
        cpu.load_program(program)

        for address, data in initial_memory:
            end = address + len(data)
            if address < 0 or end > len(cpu.memory):
                raise ValueError(f"Inicialización fuera de memoria: 0x{address:08x}")
            cpu.memory[address:end] = data

        cpu.run(max_instructions)

        return {
            "halted": cpu.halted,
            "error": cpu.error,
            "error_code": cpu.error_code,
            "pc": cpu.pc,
            "registers": {number: cpu.regs[number] for number in register_numbers},
            "memory": {
                (address, size): bytes(cpu.memory[address:address + size])
                for address, size in memory_ranges
            },
        }
