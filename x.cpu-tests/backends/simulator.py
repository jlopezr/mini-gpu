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

# RGB565 de 320x240, el mismo framebuffer que la placa.
FRAME_BYTES = 320 * 240 * 2


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Qué casos no caben aquí.

    El simulador tiene ahora la ventana de registros de vídeo y un reloj de
    frames sintético, así que acepta `video` y `frame_capture`. Lo que sigue
    sin tener es TIEMPO: no hay barrido leyendo la memoria por su cuenta, ni
    ancho de banda, ni contienda. `VideoDevice` en `minicpu_sim.py` lo explica
    entero; el resumen es que aquí se valida QUÉ dibuja un programa, nunca
    CUÁNDO.

    En concreto, `underflow` es siempre cero y no puede ser otra cosa: una
    expectativa `underflow: false` pasa aquí sin comprobar nada. Sigue mereciendo
    la pena tenerla en el caso, porque en hardware sí significa algo, pero
    conviene no confundir un verde de aquí con haber probado eso.
    """
    del case, version
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
    ) -> dict:
        del timeout_seconds  # El simulador usa un límite de instrucciones.

        dispositivo = None
        if video is not None:
            if self.video_class is None:
                raise RuntimeError(
                    f"el simulador {self.version!r} no tiene VideoDevice")
            dispositivo = self.video_class()
            swap = video.get("run_until_swap")
            if swap:
                dispositivo.halt_at = swap

        cpu = self.cpu_class(self.memory_size, video=dispositivo)
        cpu.load_program(program)

        for address, data in initial_memory:
            end = address + len(data)
            if address < 0 or end > len(cpu.memory):
                raise ValueError(f"Inicialización fuera de memoria: 0x{address:08x}")
            cpu.memory[address:end] = data

        cpu.run(max_instructions)

        resultado_video = None
        if dispositivo is not None:
            resultado_video = {
                # Siempre False, y a propósito: aquí no hay nada que pueda
                # llegar tarde. Ver VideoDevice en minicpu_sim.py.
                "underflow": False,
                "frames": dispositivo.frame_count,
                "swaps": dispositivo.swap_count,
                "fb_front": dispositivo.fb_front,
                "frame": None,
            }
            if video.get("capture_frame"):
                # Desde FB_FRONT, igual que en la placa: tras el intercambio N
                # el buffer visible alterna según la paridad.
                base = dispositivo.fb_front
                resultado_video["frame"] = bytes(
                    cpu.memory[base:base + FRAME_BYTES])

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
            "video": resultado_video,
        }
