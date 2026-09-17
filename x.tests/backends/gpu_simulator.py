"""Adaptador de MiniGPU al runner de conformidad."""

from pathlib import Path

from .simulator import _load_module

VERSIONS = {
    "cycle": {
        "simulator_path": Path("25.gpu-sim-cycle-uarch/minigpu_cycle.py"),
        "trace_path": Path("11.gpu-sim-func/gpu_trace.py"),
        "capabilities": ("atomic_warp_faults", "alu_extended", "compare",
                         "shift_immediate", "subword_memory"),
        "description": "modelo cycle-accurate S/F/I/D/X/W de la futura MiniGPU",
    },
    "current": {
        "simulator_path": Path("11.gpu-sim-func/minigpu_sim.py"),
        # Igual que en `simulator.py`, pero la lista es mas corta: al modelo de
        # GPU le siguen faltando los accesos sub-palabra y las llamadas,
        # pendientes de backport desde la MiniCPU.
        #
        # `video` SI esta, desde que `minigpu_sim.py` tiene `VideoDevice`. No
        # `frame_capture`: eso es HALT_AT, que la GPU no tiene ni en el RTL
        # --sus kernels terminan con HALT-- asi que declararlo seria mentir.
        # `atomic_warp_faults` solo la tiene el simulador: en `capabilities.json`
        # es la unica entrada sin `file`, porque no hay RTL que la implemente.
        "capabilities": ("atomic_warp_faults", "video"),
        "description": "simulador funcional MiniGPU actual",
    },
}
DEFAULT_VERSION = "current"

# RGB565 de 320x240, el mismo framebuffer que la placa.
FRAME_BYTES = 320 * 240 * 2


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene este simulador, con las implicaciones ya expandidas."""
    from .simulator import expand_for

    return expand_for(VERSIONS[version]["capabilities"])


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Que casos no caben aqui.

    Faltaba, y no era inocuo: sin esta funcion el runner NO miraba el
    `requires` de un caso de GPU contra lo que el simulador tiene, asi que un
    caso que pidiera un dispositivo ausente se ejecutaba igual y fallaba como
    si el programa estuviera mal. Los otros tres backends si lo comprobaban.
    No se habia notado porque hasta ahora ningun caso de GPU declaraba una
    capacidad que a este simulador le falte -- el primero fue el caso de video
    compartido entre familias.

    La diferencia importa: un SKIP dice «aqui no se prueba», y un FAIL dice
    «aqui esta roto». Confundirlos es justamente lo que esta maquinaria existe
    para evitar.
    """
    disponibles = capabilities(version)
    faltan = [name for name in case.get("requires", []) if name not in disponibles]
    if faltan:
        return f"el simulador de GPU {version!r} no tiene {', '.join(faltan)}"
    return None


class GpuBackend:
    ARCHITECTURE = "gpu"

    def __init__(self, repository: Path, version: str = DEFAULT_VERSION):
        if version not in VERSIONS:
            raise ValueError(f"Versión GPU desconocida: {version}")
        self.version = version
        simulator_path = repository / VERSIONS[version]["simulator_path"]
        trace_path = VERSIONS[version].get("trace_path")
        _load_module("gpu_trace", repository / trace_path if trace_path else simulator_path.with_name("gpu_trace.py"))
        self.module = _load_module(
            f"minigpu_{version}_for_tests", simulator_path
        )

    def run(self, program: bytes, initial_memory: list[tuple[int, bytes]],
            register_numbers: set[int], memory_ranges: list[tuple[int, int]],
            max_instructions: int, timeout_seconds: float, warp_config: object,
            trace: bool = False, trace_detail: bool = False,
            trace_limit: int | None = None, trace_file: Path | None = None,
            simulator_options: dict | None = None,
            video: dict | None = None) -> dict:
        # Como el backend CPU funcional, se limita por instrucciones, no por tiempo.
        del register_numbers, timeout_seconds
        dispositivo = None
        if video is not None:
            video_class = getattr(self.module, "VideoDevice", None)
            if video_class is None:
                raise RuntimeError(
                    f"el simulador de GPU {self.version!r} no tiene VideoDevice")
            if video.get("run_until_swap"):
                # HALT_AT no existe en la GPU: no se puede armar una parada por
                # intercambios. Se dice aqui en vez de aceptarlo y no pararse,
                # que acabaria en un limite de instrucciones sin explicacion.
                raise RuntimeError(
                    "run_until.swap necesita HALT_AT, que la GPU no tiene: "
                    "sus kernels terminan con HALT")
            dispositivo = video_class()
        size = self.module.config_warp_size(warp_config)
        gpu = self.module.System(warp_size=size, video=dispositivo,
                                 **(simulator_options or {}))
        gpu.load_program(program, launch=False)
        for address, data in initial_memory:
            if address < 0 or address + len(data) > len(gpu.memory):
                raise ValueError(f"Inicialización fuera de memoria: 0x{address:08x}")
            gpu.memory[address:address + len(data)] = data
        gpu.configure_warps(warp_config)
        trace_stream = None
        try:
            if trace or trace_detail or trace_limit is not None or trace_file is not None:
                import sys
                trace_stream = trace_file.open("w", encoding="utf-8") if trace_file else sys.stderr
                gpu.trace = self.module.TextTrace(
                    trace_stream, detail=trace_detail, limit=trace_limit
                )
            gpu.run(max_instructions)
        finally:
            if gpu.trace is not None:
                message = gpu.fault or ("HALT" if gpu.halted else "FIN")
                gpu.trace.finish(str(message))
            if trace_file and trace_stream is not None:
                trace_stream.close()
        observations = {"instructions_executed": gpu.instructions_executed}
        observations["fault.present"] = gpu.fault is not None
        if gpu.fault is not None:
            for field in ("pc", "warp_id", "core_id", "address"):
                observations[f"fault.{field}"] = getattr(gpu.fault, field)
        for warp in gpu.streaming_multiprocessor.warps:
            prefix = f"warp[{warp.warp_id}]"
            observations[f"{prefix}.pc"] = warp.pc
            observations[f"{prefix}.active_mask"] = warp.active_mask
            observations[f"{prefix}.instructions_executed"] = warp.instructions_executed
            for lane in warp.processors:
                for number, value in enumerate(lane.regs):
                    observations[f"{prefix}.lane[{lane.core_id}].R{number}"] = value
        resultado_video = None
        if dispositivo is not None:
            resultado_video = {
                # Siempre False, y a proposito: aqui no hay barrido que pueda
                # llegar tarde. Ver VideoDevice en minigpu_sim.py.
                "underflow": False,
                "frames": dispositivo.frame_count,
                "swaps": dispositivo.swap_count,
                "fb_front": dispositivo.fb_front,
                "frame": None,
            }
            if video.get("capture_frame"):
                # Desde FB_FRONT, igual que en la placa: tras el intercambio N
                # el buffer visible alterna segun la paridad.
                base = dispositivo.fb_front
                resultado_video["frame"] = bytes(
                    gpu.memory[base:base + FRAME_BYTES])
        return {
            "halted": gpu.halted,
            "error": gpu.error,
            "error_code": gpu.error_code,
            "registers": {},
            "video": resultado_video,
            "observations": observations,
            "memory": {(address, size): bytes(gpu.memory[address:address + size])
                       for address, size in memory_ranges},
        }
