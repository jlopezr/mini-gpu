"""Adaptador de MiniGPU al runner de conformidad."""

from pathlib import Path

from . import video_layout
from .simulator import _load_module, video_result

VERSIONS = {
    "cycle": {
        "simulator_path": Path("25.gpu-sim-cycle-uarch/minigpu_cycle.py"),
        "trace_path": Path("11.gpu-sim-func/gpu_trace.py"),
        "capabilities": ("atomic_warp_faults", "alu_extended", "compare",
                         "shift_immediate", "subword_memory", "frame_capture", "serial"),
        "description": "modelo cycle-accurate S/F/I/D/X/W de la futura MiniGPU",
    },
    "current": {
        "simulator_path": Path("11.gpu-sim-func/minigpu_sim.py"),
        # Perifericos funcionales compartidos; no implica soporte en la FPGA.
        "capabilities": ("atomic_warp_faults", "frame_capture", "serial"),
        "description": "simulador funcional MiniGPU actual",
    },
}
DEFAULT_VERSION = "current"


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
            video: dict | None = None, stdin: bytes = b"") -> dict:
        # Como el backend CPU funcional, se limita por instrucciones, no por tiempo.
        del register_numbers, timeout_seconds
        dispositivo = None
        if video is not None:
            video_class = getattr(self.module, "VideoDevice", None)
            if video_class is None:
                raise RuntimeError(
                    f"el simulador de GPU {self.version!r} no tiene VideoDevice")
            dispositivo = video_class()
            if video.get("run_until_swap"):
                dispositivo.write(dispositivo.HALT_AT, video["run_until_swap"])
            # Igual que en los otros dos backends: el dispositivo arranca con
            # las bases a cero, como el hardware, y es el arnes quien elige
            # donde vive el framebuffer. Ver backends/video_layout.py.
            dispositivo.write(dispositivo.FB_FRONT, video_layout.FB_FRONT)
            dispositivo.write(dispositivo.FB_BACK, video_layout.FB_BACK)
        size = self.module.config_warp_size(warp_config)
        serie = self.module.SerialDevice(stdin=stdin)
        serie.attach_host()
        gpu = self.module.System(warp_size=size, video=dispositivo, serial=serie,
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
        resultado_video = video_result(gpu, bool(video and video.get("capture_frame")))
        return {
            "halted": gpu.halted,
            "error": gpu.error,
            "error_code": gpu.error_code,
            "registers": {},
            "video": resultado_video,
            "stdout": serie.output(),
            "observations": observations,
            "memory": {(address, size): bytes(gpu.memory[address:address + size])
                       for address, size in memory_ranges},
        }
