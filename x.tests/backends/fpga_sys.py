"""Backend de la GPU de un prototipo CPU+GPU (GPU CORE), lanzada por el host.

En la 36 y la 37 el monitor gobierna la CPU, no la GPU: la GPU es un
coprocesador que lanza la CPU escribiendo `GPU_CONTROL` y los descriptores de
warp por MMIO (mmio.md §14). `fpga_gpu.py` no sirve ahí --solo registra las
carpetas sin `cpu.v`--, y no debe: esas dos carpetas siguen siendo CPU para
`fpga-cpu`, el SYS_ID y los informes. Este backend las trata como lo que también
son, una GPU.

No ejecuta ningún programa de CPU. El host hace de CPU: con la CPU parada
escribe el kernel y los datos en la RAM compartida (`write_memory`), los
descriptores y `GPU_CONTROL` por `write_word`, y sondea `WARP_DONE` y
`GPU_STATUS` por `read_word`. El monitor llega al MMIO de la GPU por el mismo
mux que la CPU (comprobado en la 36 el 2026-10-10).

QUÉ SE PUEDE OBSERVAR. Solo lo que `gpu_system.v` expone por MMIO: el estado de
la GPU, el primer fallo, las instrucciones retiradas (total y por warp) y la
memoria. NO se expone el PC de ejecución de cada warp (`PC` en el descriptor es
lo que se escribió, no el actual), ni su máscara de lanes viva, ni los registros
de las lanes. Un caso que los pide se omite con motivo en `incompatibility`;
nunca se sustituye una observación por el valor esperado. Ver
`x.tests/backend-fpga-sys.md`.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from . import board
from .common import capabilities_of, load_module as _load_module
from .fpga_common import (
    REPOSITORY as _REPOSITORY, MonitorBackend, architectural_size, build_versions,
)

from tools.mmio_map import (  # noqa: E402
    MMIO_GPU_BASE,
    MMIO_GPU_CONTROL_OFF,
    MMIO_GPU_SIMT_BASE,
    MMIO_GPU_SIMT_CONTEXT_OFF,
    MMIO_GPU_SIMT_FIRST_ERROR_OFF,
    MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF,
    MMIO_GPU_SIMT_WARP_RETIRED_OFF,
    MMIO_GPU_STATUS_OFF,
    MMIO_GPU_WARP_DONE_OFF,
    MMIO_GPU_WARPS_ACTIVE_OFF,
    MMIO_GPU_WARPS_ARG_OFF,
    MMIO_GPU_WARPS_BASE,
    MMIO_GPU_WARPS_GROUP_OFF,
    MMIO_GPU_WARPS_LOGICAL_ID_OFF,
    MMIO_GPU_WARPS_PC_OFF,
    MMIO_GPU_WARPS_STRIDE,
    MMIO_GPU_PERF_BASE,
)
from tools.rtl_facts import (  # noqa: E402
    backends_from_rtl,
    capabilities_from_rtl,
    capability_architectures,
    capability_files,
)

# GPU_CONTROL (mmio.md §14.1): comandos, no estado.
CTRL_RUN = 1 << 0
CTRL_HALT = 1 << 1
CTRL_RESET = 1 << 4
# GPU_STATUS.
STATUS_RUNNING = 1 << 0
STATUS_HALTED = 1 << 1
STATUS_IDLE = 1 << 2
STATUS_ERROR = 1 << 3
# El código de GPU_SIMT_DEBUG.FIRST_ERROR para un fallo de acceso a memoria: la
# dirección efectiva no se conserva en ningún prototipo.
ERROR_MEMORY_ACCESS = 2
WARPS = 8
# Lo que tarda el host en volver a mirar. Un viaje por serie ya son ~2 ms.
POLL_SECONDS = 0.005

GPU_STATUS = MMIO_GPU_BASE + MMIO_GPU_STATUS_OFF
GPU_CONTROL = MMIO_GPU_BASE + MMIO_GPU_CONTROL_OFF
WARP_DONE = MMIO_GPU_BASE + MMIO_GPU_WARP_DONE_OFF
SIMT_CONTEXT = MMIO_GPU_SIMT_BASE + MMIO_GPU_SIMT_CONTEXT_OFF
SIMT_FIRST_ERROR = MMIO_GPU_SIMT_BASE + MMIO_GPU_SIMT_FIRST_ERROR_OFF
SIMT_FIRST_ERROR_PC = MMIO_GPU_SIMT_BASE + MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF
SIMT_WARP_RETIRED = MMIO_GPU_SIMT_BASE + MMIO_GPU_SIMT_WARP_RETIRED_OFF
# GPU PERFORMANCE (§14.4): ciclos en +0x00 y el contador GLOBAL de retiros en +0x04.
PERF_CYCLES = MMIO_GPU_PERF_BASE
PERF_RETIRED = MMIO_GPU_PERF_BASE + 0x04

# Observaciones que el RTL de hoy no deja leer, y cómo se llaman para el motivo.
_UNOBSERVABLE = (
    (re.compile(r"^warp\[\d+\]\.pc$"), "el PC final de los warps"),
    (re.compile(r"^warp\[\d+\]\.active_mask$"), "la máscara de lanes viva de los warps"),
    (re.compile(r"^warp\[\d+\]\.lane\[\d+\]\.R\d+$"), "los registros de las lanes"),
)


def _is_gpu_file(name: str) -> bool:
    """Un fichero que es de la GPU y no de la CPU de al lado.

    En una carpeta con `cpu.v` y `gpu_system.v`, una capacidad con `file:
    ["cpu.v", "gpu_lane.v"]` se detectaría en `cpu.v` y se atribuiría a la GPU
    aunque su lane no la tenga. Por eso solo se miran los ficheros `gpu_*.v`.
    El vídeo, el puerto serie y el INPUT son de la CPU: un warp que toque MMIO
    recibe error (`gpu_system.v`), así que no son capacidades de esta GPU.
    """
    return name.startswith("gpu_") and name.endswith(".v") and not name.endswith("_tb.v")


def gpu_capabilities(directory: Path, signals: dict) -> tuple[str, ...]:
    """Las capacidades de la GPU de una carpeta CPU+GPU, sin las de su CPU."""
    restricted = {}
    for name, spec in signals.items():
        if "gpu" not in capability_architectures(spec):
            continue
        files = [f for f in capability_files(spec) if _is_gpu_file(f)]
        # La memoria grande es de todo el sistema: la GPU direcciona la misma
        # SDRAM que la CPU, y su controlador no se llama `gpu_*`.
        if name == "large_memory":
            files = list(capability_files(spec))
        if files:
            restricted[name] = dict(spec, file=files)
    return capabilities_from_rtl(directory, restricted)


def _select(directory: Path) -> bool:
    """Solo las carpetas con CPU y GPU a la vez, y con el puente que cruza el
    bus de la CPU al de la GPU: sin él el host tampoco llega a GPU CORE."""
    return (backends_from_rtl(directory) == ("cpu", "gpu")
            and (directory / "gpu_mmio_bridge.v").exists())

VERSIONS = build_versions(_select, gpu_capabilities)
# La más reciente: es la que tiene más contrato de GPU CORE.
DEFAULT_VERSION = next(reversed(VERSIONS), "")


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene la GPU de esta versión, con las implicaciones expandidas."""
    return capabilities_of(VERSIONS, version)


_MODEL = {}


def _model():
    """El simulador funcional, solo para validar el lanzamiento como el monitor."""
    if "modulo" not in _MODEL:
        path = _REPOSITORY / "11.gpu-sim-func" / "minigpu_sim.py"
        if "gpu_trace" not in sys.modules:
            _load_module("gpu_trace", path.with_name("gpu_trace.py"))
        _MODEL["modulo"] = _load_module("gpu_core_launch_validation", path)
    return _MODEL["modulo"]


def _case_warps(warp_config, memory_size: int):
    """Los warps ya normalizados por el modelo, que es quien valida el JSON."""
    model = _model().System(memory_size, 8, 8)
    model.configure_warps(warp_config)
    return model.streaming_multiprocessor.warps


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Rechaza antes de abrir el puerto lo que esta GPU no puede comprobar."""
    config = VERSIONS[version]
    if case.get("simulator_options"):
        return "las profundidades SIMT del caso requieren el simulador"
    if "atomic_warp_faults" in case.get("requires", []):
        return "el caso exige fallos atómicos por warp; el RTL permite efectos parciales"
    available = capabilities(version)
    missing = [name for name in case.get("requires", []) if name not in available]
    if missing:
        return f"sin {', '.join(missing)}"
    # El vídeo es de la CPU: la GPU de esta carpeta no es maestro de MMIO.
    if (case.get("run_until") or case["expected"].get("video") is not None
            or case["expected"].get("frame") is not None):
        return "el vídeo es de la CPU; esta GPU no es maestro de MMIO"
    monitor_path = _REPOSITORY / config["monitor_path"]
    monitor = _load_module(f"gpu_core_monitor_{version}_for_regions", monitor_path)
    reason = board.region_incompatibility(case, monitor.ARCHITECTURAL_REGIONS)
    if reason:
        return reason
    observations = case["expected"].get("observations", {})
    if observations.get("fault.address") is not None or (
        "fault.address" in observations
        and case["expected"]["error_code"] == ERROR_MEMORY_ACCESS
    ):
        return "el monitor no expone la dirección efectiva de un fallo"
    unavailable = []
    for pattern, name in _UNOBSERVABLE:
        if any(pattern.match(key) for key in observations) and name not in unavailable:
            unavailable.append(name)
    if unavailable:
        return (f"el RTL de {version} no expone {' ni '.join(unavailable)} "
                "(GPU SIMT DEBUG solo da instrucciones retiradas y el primer fallo)")
    try:
        warps = _case_warps(case["warp_config"], architectural_size(monitor))
        if any(w.workgroup_id > 0xFFFF_FFFF for w in warps):
            return "workgroup_id no cabe en 32 bits"
    except (ValueError, TypeError) as error:
        return f"lanzamiento incompatible con FPGA: {error}"
    return None


def configure_and_launch(client, warps) -> int:
    """RESET, descriptores y RUN. Devuelve la máscara de warps lanzados.

    Es la secuencia de `cases-cpu/gpu/launch-run`, que corre en la 36 y en la 37:

      * RESET primero, para no heredar errores, WARP_DONE ni pilas del caso
        anterior (la GPU sigue ahí entre un caso y otro). Reinicia el banco de
        registros en 256 ciclos de GPU, muchos menos que un viaje por serie, así
        que no hace falta esperar.
      * Se escriben los OCHO descriptores, también los de los warps que no
        participan: desde el hito 2 RESET conserva los descriptores, y un warp
        con `ACTIVE != 0` de un caso anterior arrancaría con RUN.
      * `ACTIVE` va el último de cada descriptor: en el hito 1 escribirlo hace
        vivo al warp, y escribir un descriptor de un warp vivo es un error.
    """
    client.write_word(GPU_CONTROL, CTRL_RESET)
    by_id = {w.warp_id: w for w in warps}
    launched = 0
    for warp_id in range(WARPS):
        base = MMIO_GPU_WARPS_BASE + warp_id * MMIO_GPU_WARPS_STRIDE
        warp = by_id.get(warp_id)
        pc = warp.pc if warp else 0
        group = warp.workgroup_id if warp else 0
        active = warp.active_mask if warp else 0
        logical = (warp.logical_warp_id or 0) if warp else 0
        argument = (warp.arg or 0) if warp else 0
        client.write_word(base + MMIO_GPU_WARPS_PC_OFF, pc)
        client.write_word(base + MMIO_GPU_WARPS_GROUP_OFF, group)
        client.write_word(MMIO_GPU_WARPS_BASE + MMIO_GPU_WARPS_LOGICAL_ID_OFF
                          + warp_id * 4, logical)
        client.write_word(MMIO_GPU_WARPS_BASE + MMIO_GPU_WARPS_ARG_OFF
                          + warp_id * 4, argument)
        client.write_word(base + MMIO_GPU_WARPS_ACTIVE_OFF, active)
        if active:
            launched |= 1 << warp_id
    if launched:
        client.write_word(GPU_CONTROL, CTRL_RUN)
    return launched


def wait_for_kernel(client, launched: int, timeout_seconds: float,
                    clock=time.monotonic, sleep=time.sleep) -> int:
    """Espera a que acaben los warps lanzados o a que la GPU falle.

    Se mira `WARP_DONE` y no solo `IDLE`: justo después de `RUN` el estado puede
    seguir diciendo IDLE un ciclo, porque el lanzamiento es un pulso registrado.
    `WARP_DONE` es pegajoso, así que el evento no se pierde aunque se tarde en
    mirarlo. Devuelve el último `GPU_STATUS`.
    """
    limit = clock() + timeout_seconds
    while True:
        done = client.read_word(WARP_DONE) & 0xFF
        state = client.read_word(GPU_STATUS)
        if state & STATUS_ERROR:
            return state
        if launched == 0 or (done & launched) == launched:
            # Los warps han acabado; falta que la GPU se pare del todo antes de
            # que el host lea la memoria.
            if not state & STATUS_RUNNING:
                return state
        if clock() >= limit:
            client.write_word(GPU_CONTROL, CTRL_HALT)
            raise TimeoutError(
                f"La GPU no terminó en {timeout_seconds:g} segundos")
        sleep(POLL_SECONDS)


def read_observations(client, state: int, requested: set[str]) -> tuple[dict, int]:
    """`(observaciones, error_code)`: lo que el RTL deja leer.

    Solo se paga por serie lo pedido: los contadores por warp cuestan una
    escritura de CONTEXT y una lectura cada uno.
    """
    error = bool(state & STATUS_ERROR)
    result = {
        "fault.present": error,
        "instructions_executed": client.read_word(PERF_RETIRED),
    }
    code = 0
    if error:
        diagnostic = client.read_word(SIMT_FIRST_ERROR)
        code = (diagnostic >> 8) & 0xFF
        result.update({
            "fault.pc": client.read_word(SIMT_FIRST_ERROR_PC),
            "fault.warp_id": (diagnostic >> 3) & 7,
            "fault.core_id": diagnostic & 7 if diagnostic & 0x40 else None,
        })
        # Solo los fallos que no son de dirección tienen una dirección efectiva
        # arquitectónicamente nula. Nunca se inventa una que el RTL no guarda.
        if code != ERROR_MEMORY_ACCESS:
            result["fault.address"] = None
    for warp in range(WARPS):
        if f"warp[{warp}].instructions_executed" in requested:
            client.write_word(SIMT_CONTEXT, warp << 3)
            result[f"warp[{warp}].instructions_executed"] = client.read_word(
                SIMT_WARP_RETIRED)
    return result, code


class FpgaSysBackend(MonitorBackend):
    """Carga, lanza e inspecciona un caso GPU en la GPU de una CPU+GPU."""

    ARCHITECTURE = "gpu"
    NAME = "fpga-sys"
    VERSIONS = VERSIONS
    DEFAULT_VERSION = DEFAULT_VERSION
    def _run_once(
        self,
        program: bytes,
        initial_memory: list[tuple[int, bytes]],
        register_numbers: set[int],
        memory_ranges: list[tuple[int, int]],
        max_instructions: int,
        timeout_seconds: float,
        warp_config: object,
        observation_fields: set[str] | None = None,
        video: dict | None = None,
    ) -> dict:
        # La placa se limita por tiempo de pared, no por instrucciones, y los
        # registros de las lanes no se leen (ver el docstring del módulo).
        del max_instructions, register_numbers
        if video is not None:
            raise ValueError("fpga-sys no ejecuta casos de vídeo")

        with self.connect() as client:
            # La CPU no corre nunca: el host hace de CPU. Parada, y con ella la
            # RAM es del monitor.
            client.halt_cpu()
            client.write_memory(0, program)
            for address, data in initial_memory:
                client.write_memory(address, data)

            warps = _case_warps(
                warp_config, architectural_size(self.monitor))
            launched = configure_and_launch(client, warps)
            started = time.monotonic()
            state = wait_for_kernel(client, launched, timeout_seconds)
            elapsed = time.monotonic() - started
            if launched:
                # W1C: los warps ya consumidos, como hace launch-run.
                client.write_word(WARP_DONE, launched)

            observations, error_code = read_observations(
                client, state, observation_fields or set())
            observations["duration_seconds"] = elapsed
            cycles = client.read_word(PERF_CYCLES)
            memory = {
                (address, size): client.read_memory(address, size)
                for address, size in memory_ranges
            }

        return {
            "halted": not state & STATUS_RUNNING,
            "error": bool(state & STATUS_ERROR),
            "error_code": error_code,
            "pc": observations.get("fault.pc", 0),
            "registers": {},
            "cycles": cycles,
            "instructions": observations["instructions_executed"],
            "clock_hz": self.configuration.get("clock_hz"),
            "stalls": None,
            "video": None,
            "observations": observations,
            "memory": memory,
        }
