"""Backend del simulador funcional para los tests comunes de CPU."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


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

    def __init__(self, repository: Path, memory_size: int = 2 * 1024 * 1024):
        module = _load_module(
            "minicpu_sim_for_tests",
            repository / "2.cpu-sim-func" / "minicpu_sim.py",
        )
        self.cpu_class = module.CPU
        self.memory_size = memory_size

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
