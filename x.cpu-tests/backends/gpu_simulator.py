"""Adaptador de MiniGPU al runner de conformidad."""

from pathlib import Path

from .simulator import _load_module

VERSIONS = {
    "current": {"simulator_path": Path("11.gpu-sim-func/minigpu_sim.py")},
}
DEFAULT_VERSION = "current"


class GpuBackend:
    ARCHITECTURE = "gpu"

    def __init__(self, repository: Path, version: str = DEFAULT_VERSION):
        if version not in VERSIONS:
            raise ValueError(f"Versión GPU desconocida: {version}")
        simulator_path = repository / VERSIONS[version]["simulator_path"]
        _load_module("gpu_trace", simulator_path.with_name("gpu_trace.py"))
        self.module = _load_module(
            f"minigpu_{version}_for_tests", simulator_path
        )

    def run(self, program: bytes, initial_memory: list[tuple[int, bytes]],
            register_numbers: set[int], memory_ranges: list[tuple[int, int]],
            max_instructions: int, timeout_seconds: float, warp_config: object,
            trace: bool = False, trace_detail: bool = False,
            trace_limit: int | None = None, trace_file: Path | None = None) -> dict:
        # Como el backend CPU funcional, se limita por instrucciones, no por tiempo.
        del register_numbers, timeout_seconds
        size = self.module.config_warp_size(warp_config)
        gpu = self.module.System(warp_size=size)
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
        return {
            "halted": gpu.halted,
            "error": gpu.error,
            "error_code": gpu.error_code,
            "registers": {},
            "observations": observations,
            "memory": {(address, size): bytes(gpu.memory[address:address + size])
                       for address, size in memory_ranges},
        }
