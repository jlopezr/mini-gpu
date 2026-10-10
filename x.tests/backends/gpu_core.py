"""Backend de la GPU de un prototipo CPU+GPU (GPU CORE), lanzada por el host.

En la 36 y la 37 el monitor gobierna la CPU, no la GPU: la GPU es un
coprocesador que lanza la CPU escribiendo `GPU_CONTROL` y los descriptores de
warp por MMIO (mmio.md §14). `gpu_fpga.py` no sirve ahí --solo registra las
carpetas sin `cpu.v`--, y no debe: esas dos carpetas siguen siendo CPU para
`cpu-fpga`, el SYS_ID y los informes. Este backend las trata como lo que también
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
`x.tests/backend-gpu-core.md`.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from . import board
from .gpu_fpga import _load_module, architectural_size, expand_for

_REPOSITORY = Path(__file__).resolve().parents[2]
if str(_REPOSITORY) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY))

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
    clock_hz_from_rtl,
    load_capability_signals,
    monitor_version_from_rtl,
    readme_title,
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
_NO_OBSERVABLES = (
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
    restringidas = {}
    for name, spec in signals.items():
        if "gpu" not in capability_architectures(spec):
            continue
        ficheros = [f for f in capability_files(spec) if _is_gpu_file(f)]
        # La memoria grande es de todo el sistema: la GPU direcciona la misma
        # SDRAM que la CPU, y su controlador no se llama `gpu_*`.
        if name == "large_memory":
            ficheros = list(capability_files(spec))
        if ficheros:
            restringidas[name] = dict(spec, file=ficheros)
    return capabilities_from_rtl(directory, restringidas)


def _prototype_number(directory: Path) -> int:
    match = re.match(r"(\d+)", directory.name)
    return int(match.group(1)) if match else 0


def _build_versions() -> dict:
    signals = load_capability_signals(_REPOSITORY)
    manifests = sorted(
        _REPOSITORY.glob("*/version.json"), key=lambda p: _prototype_number(p.parent)
    )
    versions = {}
    for manifest_path in manifests:
        directory = manifest_path.parent
        # Solo las carpetas con CPU y GPU a la vez, y con el puente que cruza el
        # bus de la CPU al de la GPU: sin él el host tampoco llega a GPU CORE.
        if backends_from_rtl(directory) != ("cpu", "gpu"):
            continue
        if not (directory / "gpu_mmio_bridge.v").exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        monitor_version = monitor_version_from_rtl(directory)
        if monitor_version is None:
            raise RuntimeError(
                f"no se pudo leer VERSION_MAJOR/VERSION_MINOR de "
                f"{directory / 'monitor.v'}"
            )
        entry = {
            "monitor_path": directory.relative_to(_REPOSITORY) / "monitor.py",
            "monitor_version": monitor_version,
            "description": manifest.get("description") or readme_title(directory),
            "capabilities": gpu_capabilities(directory, signals),
        }
        clock_hz = clock_hz_from_rtl(directory)
        if clock_hz is not None:
            entry["clock_hz"] = clock_hz
        versions[manifest["alias"]] = entry
    return versions


VERSIONS = _build_versions()
# La más reciente: es la que tiene más contrato de GPU CORE.
DEFAULT_VERSION = next(reversed(VERSIONS), "")


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene la GPU de esta versión, con las implicaciones expandidas."""
    return expand_for(VERSIONS[version]["capabilities"])


_MODELO = {}


def _modelo():
    """El simulador funcional, solo para validar el lanzamiento como el monitor."""
    if "modulo" not in _MODELO:
        ruta = _REPOSITORY / "11.gpu-sim-func" / "minigpu_sim.py"
        if "gpu_trace" not in sys.modules:
            _load_module("gpu_trace", ruta.with_name("gpu_trace.py"))
        _MODELO["modulo"] = _load_module("gpu_core_launch_validation", ruta)
    return _MODELO["modulo"]


def _warps_del_caso(warp_config, memory_size: int):
    """Los warps ya normalizados por el modelo, que es quien valida el JSON."""
    modelo = _modelo().System(memory_size, 8, 8)
    modelo.configure_warps(warp_config)
    return modelo.streaming_multiprocessor.warps


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Rechaza antes de abrir el puerto lo que esta GPU no puede comprobar."""
    config = VERSIONS[version]
    if case.get("simulator_options"):
        return "las profundidades SIMT del caso requieren el simulador"
    if "atomic_warp_faults" in case.get("requires", []):
        return "el caso exige fallos atómicos por warp; el RTL permite efectos parciales"
    disponibles = capabilities(version)
    faltan = [name for name in case.get("requires", []) if name not in disponibles]
    if faltan:
        return f"sin {', '.join(faltan)}"
    # El vídeo es de la CPU: la GPU de esta carpeta no es maestro de MMIO.
    if (case.get("run_until") or case["expected"].get("video") is not None
            or case["expected"].get("frame") is not None):
        return "el vídeo es de la CPU; esta GPU no es maestro de MMIO"
    monitor_path = _REPOSITORY / config["monitor_path"]
    monitor = _load_module(f"gpu_core_monitor_{version}_for_regions", monitor_path)
    reason = board.region_incompatibility(case, monitor.ARCHITECTURAL_REGIONS)
    if reason:
        return reason
    observaciones = case["expected"].get("observations", {})
    if observaciones.get("fault.address") is not None or (
        "fault.address" in observaciones
        and case["expected"]["error_code"] == ERROR_MEMORY_ACCESS
    ):
        return "el monitor no expone la dirección efectiva de un fallo"
    ausentes = []
    for patron, nombre in _NO_OBSERVABLES:
        if any(patron.match(clave) for clave in observaciones) and nombre not in ausentes:
            ausentes.append(nombre)
    if ausentes:
        return (f"el RTL de {version} no expone {' ni '.join(ausentes)} "
                "(GPU SIMT DEBUG solo da instrucciones retiradas y el primer fallo)")
    try:
        warps = _warps_del_caso(case["warp_config"], architectural_size(monitor))
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
    por_id = {w.warp_id: w for w in warps}
    lanzados = 0
    for warp_id in range(WARPS):
        base = MMIO_GPU_WARPS_BASE + warp_id * MMIO_GPU_WARPS_STRIDE
        warp = por_id.get(warp_id)
        pc = warp.pc if warp else 0
        grupo = warp.workgroup_id if warp else 0
        activo = warp.active_mask if warp else 0
        logico = (warp.logical_warp_id or 0) if warp else 0
        argumento = (warp.arg or 0) if warp else 0
        client.write_word(base + MMIO_GPU_WARPS_PC_OFF, pc)
        client.write_word(base + MMIO_GPU_WARPS_GROUP_OFF, grupo)
        client.write_word(MMIO_GPU_WARPS_BASE + MMIO_GPU_WARPS_LOGICAL_ID_OFF
                          + warp_id * 4, logico)
        client.write_word(MMIO_GPU_WARPS_BASE + MMIO_GPU_WARPS_ARG_OFF
                          + warp_id * 4, argumento)
        client.write_word(base + MMIO_GPU_WARPS_ACTIVE_OFF, activo)
        if activo:
            lanzados |= 1 << warp_id
    if lanzados:
        client.write_word(GPU_CONTROL, CTRL_RUN)
    return lanzados


def wait_for_kernel(client, lanzados: int, timeout_seconds: float,
                    clock=time.monotonic, sleep=time.sleep) -> int:
    """Espera a que acaben los warps lanzados o a que la GPU falle.

    Se mira `WARP_DONE` y no solo `IDLE`: justo después de `RUN` el estado puede
    seguir diciendo IDLE un ciclo, porque el lanzamiento es un pulso registrado.
    `WARP_DONE` es pegajoso, así que el evento no se pierde aunque se tarde en
    mirarlo. Devuelve el último `GPU_STATUS`.
    """
    limite = clock() + timeout_seconds
    while True:
        hechos = client.read_word(WARP_DONE) & 0xFF
        estado = client.read_word(GPU_STATUS)
        if estado & STATUS_ERROR:
            return estado
        if lanzados == 0 or (hechos & lanzados) == lanzados:
            # Los warps han acabado; falta que la GPU se pare del todo antes de
            # que el host lea la memoria.
            if not estado & STATUS_RUNNING:
                return estado
        if clock() >= limite:
            client.write_word(GPU_CONTROL, CTRL_HALT)
            raise TimeoutError(
                f"La GPU no terminó en {timeout_seconds:g} segundos")
        sleep(POLL_SECONDS)


def read_observations(client, estado: int, requested: set[str]) -> tuple[dict, int]:
    """`(observaciones, error_code)`: lo que el RTL deja leer.

    Solo se paga por serie lo pedido: los contadores por warp cuestan una
    escritura de CONTEXT y una lectura cada uno.
    """
    error = bool(estado & STATUS_ERROR)
    resultado = {
        "fault.present": error,
        "instructions_executed": client.read_word(PERF_RETIRED),
    }
    codigo = 0
    if error:
        diagnostico = client.read_word(SIMT_FIRST_ERROR)
        codigo = (diagnostico >> 8) & 0xFF
        resultado.update({
            "fault.pc": client.read_word(SIMT_FIRST_ERROR_PC),
            "fault.warp_id": (diagnostico >> 3) & 7,
            "fault.core_id": diagnostico & 7 if diagnostico & 0x40 else None,
        })
        # Solo los fallos que no son de dirección tienen una dirección efectiva
        # arquitectónicamente nula. Nunca se inventa una que el RTL no guarda.
        if codigo != ERROR_MEMORY_ACCESS:
            resultado["fault.address"] = None
    for warp in range(WARPS):
        if f"warp[{warp}].instructions_executed" in requested:
            client.write_word(SIMT_CONTEXT, warp << 3)
            resultado[f"warp[{warp}].instructions_executed"] = client.read_word(
                SIMT_WARP_RETIRED)
    return resultado, codigo


class GpuCoreBackend:
    """Carga, lanza e inspecciona un caso GPU en la GPU de una CPU+GPU."""

    ARCHITECTURE = "gpu"

    def __init__(
        self,
        repository: Path,
        port: str,
        serial_timeout: float,
        version: str = DEFAULT_VERSION,
        upload_policy: board.UploadPolicy | None = None,
    ):
        try:
            self.configuration = VERSIONS[version]
        except KeyError as error:
            choices = ", ".join(sorted(VERSIONS))
            raise ValueError(
                f"Versión del backend gpu-core desconocida {version!r}; "
                f"opciones: {choices}"
            ) from error

        self.version = version
        self.monitor = _load_module(
            f"gpu_core_monitor_{version}_for_tests",
            repository / self.configuration["monitor_path"],
        )
        self.port = port
        self.serial_timeout = serial_timeout
        board.ensure_bitstream(
            self.monitor, port, serial_timeout,
            self.configuration["monitor_version"],
            repository / self.configuration["monitor_path"].parent,
            "gpu-core", version, upload_policy or board.UploadPolicy(),
        )

    def run(
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
            raise ValueError("gpu-core no ejecuta casos de vídeo")

        serial = self.monitor.serial
        with serial.Serial(
            port=self.port,
            baudrate=self.monitor.BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.serial_timeout,
            write_timeout=self.serial_timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as connection:
            client = self.monitor.MonitorClient(connection)
            actual = client.get_version()
            esperado = self.configuration["monitor_version"]
            if (actual.major, actual.minor) != esperado:
                raise RuntimeError(
                    f"La FPGA conectada responde con monitor {actual}, "
                    f"pero --version gpu-core={self.version} requiere "
                    f"{'.'.join(map(str, esperado))}. Carga el bitstream "
                    "correspondiente."
                )

            # La CPU no corre nunca: el host hace de CPU. Parada, y con ella la
            # RAM es del monitor.
            client.halt_cpu()
            client.write_memory(0, program)
            for address, data in initial_memory:
                client.write_memory(address, data)

            warps = _warps_del_caso(
                warp_config, architectural_size(self.monitor))
            lanzados = configure_and_launch(client, warps)
            started = time.monotonic()
            estado = wait_for_kernel(client, lanzados, timeout_seconds)
            elapsed = time.monotonic() - started
            if lanzados:
                # W1C: los warps ya consumidos, como hace launch-run.
                client.write_word(WARP_DONE, lanzados)

            observaciones, codigo_error = read_observations(
                client, estado, observation_fields or set())
            observaciones["duration_seconds"] = elapsed
            ciclos = client.read_word(PERF_CYCLES)
            memoria = {
                (address, size): client.read_memory(address, size)
                for address, size in memory_ranges
            }

        return {
            "halted": not estado & STATUS_RUNNING,
            "error": bool(estado & STATUS_ERROR),
            "error_code": codigo_error,
            "pc": observaciones.get("fault.pc", 0),
            "registers": {},
            "cycles": ciclos,
            "instructions": observaciones["instructions_executed"],
            "clock_hz": self.configuration.get("clock_hz"),
            "stalls": None,
            "video": None,
            "observations": observaciones,
            "memory": memoria,
        }
