"""Backend de MiniGPU en FPGA, sobre el cliente del monitor UART 2.1.

Es un backend propio y no una versión de `fpga.py` porque el runner lee
`ARCHITECTURE` del atributo de clase al construir `BACKEND_DEFINITIONS`, antes
de que exista una versión seleccionada: la arquitectura no puede depender de
`--version`. En este repositorio "versión" significa revisión de hardware de la
misma arquitectura (`ebr` y `sdram` son ambas CPU), igual que `simulator.py` y
`gpu_simulator.py` ya están separados por la misma razón.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from types import ModuleType

from . import board

_REPOSITORY = Path(__file__).resolve().parents[2]
if str(_REPOSITORY) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY))

from tools.rtl_facts import (  # noqa: E402
    backend_from_rtl,
    monitor_version_from_rtl,
    readme_title,
)


# Igual que en fpga.py: cada versión es una carpeta de prototipo con
# `version.json` (`{"alias": ...}`, y opcionalmente `"description"` si el
# título del README no basta); eso es lo único a mano. `monitor_version` se
# lee del RTL --ver tools/rtl_facts.py--. El backport de R0 cableado a cero
# subio las tres versiones de GPU: 12 a 2.3, y
# 14 y 17 a 2.4. No cambia ni un byte del protocolo; sube porque el cambio es
# INCOMPATIBLE y un bitstream viejo no para con error, da otro resultado en
# silencio. 14 y 17 siguen compartiendo numero, como antes: son funcionalmente
# identicas y solo se diferencian en el camino critico -y por eso 17 no tiene
# `version.json`: no es un target de test soportado, aunque tenga RTL-.
def _prototype_number(directory: Path) -> int:
    match = re.match(r"(\d+)", directory.name)
    return int(match.group(1)) if match else 0


def _build_versions() -> dict:
    manifests = sorted(
        _REPOSITORY.glob("*/version.json"), key=lambda p: _prototype_number(p.parent)
    )
    versions = {}
    for manifest_path in manifests:
        directory = manifest_path.parent
        if backend_from_rtl(directory) != "gpu":
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        monitor_version = monitor_version_from_rtl(directory)
        if monitor_version is None:
            raise RuntimeError(
                f"no se pudo leer VERSION_MAJOR/VERSION_MINOR de "
                f"{directory / 'monitor.v'}"
            )
        versions[manifest["alias"]] = {
            "monitor_path": directory.relative_to(_REPOSITORY) / "monitor.py",
            "monitor_version": monitor_version,
            "description": manifest.get("description") or readme_title(directory),
        }
    return versions


VERSIONS = _build_versions()
DEFAULT_VERSION = "bram"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def architectural_size(monitor: ModuleType) -> int:
    """Tamaño del espacio arquitectónico que declara un monitor."""
    return max(end for _, end in monitor.ARCHITECTURAL_REGIONS)


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Reject unavailable capabilities before opening a port or uploading."""
    config = VERSIONS[version]
    if case.get('simulator_options'):
        return 'las profundidades SIMT del caso requieren el simulador'
    if 'atomic_warp_faults' in case.get('requires', []):
        return 'el caso exige fallos atómicos por warp; el RTL permite efectos parciales'
    # El mapa lo declara el monitor de esta versión, que es quien lo implementa.
    monitor = _load_module(
        f'gpu_fpga_monitor_{version}_for_regions',
        Path(__file__).resolve().parents[2] / config['monitor_path'],
    )
    reason = board.region_incompatibility(case, monitor.ARCHITECTURAL_REGIONS)
    if reason:
        return reason
    observations = case['expected'].get('observations', {})
    if observations.get('fault.address') is not None or (
        'fault.address' in observations and case['expected']['error_code'] == 2
    ):
        return 'el monitor no expone la dirección efectiva de un fallo'
    # Use the same launch validator as the monitor, without touching hardware.
    model_path = Path(__file__).resolve().parents[2] / '11.gpu-sim-func/minigpu_sim.py'
    if 'gpu_trace' not in sys.modules:
        _load_module('gpu_trace', model_path.with_name('gpu_trace.py'))
    model_module = _load_module('gpu_fpga_launch_validation', model_path)
    try:
        model = model_module.System(architectural_size(monitor), 8, 8)
        model.configure_warps(case['warp_config'])
        if any(w.workgroup_id > 0xffffffff for w in model.streaming_multiprocessor.warps):
            return 'workgroup_id no cabe en 32 bits'
    except (ValueError, TypeError) as error:
        return f'lanzamiento incompatible con FPGA: {error}'
    return None


def read_observations(client, status, requested: set[str]) -> dict:
    """Read actual hardware state; register traffic is limited to assertions."""
    def word(address):
        return int.from_bytes(client.read_memory(address, 4), 'little')

    result = {'fault.present': status.error, 'instructions_executed': word(0x80000108)}
    if status.error:
        diagnostic = word(0x8000010c)
        result.update({
            'fault.pc': word(0x80000110),
            'fault.warp_id': (diagnostic >> 3) & 7,
            'fault.core_id': diagnostic & 7 if diagnostic & 0x40 else None,
        })
        # Only non-address faults have an architectural null address. Never
        # invent an effective memory address that this RTL does not retain.
        if status.error_code != 2:
            result['fault.address'] = None
    for warp in range(8):
        prefix = f'warp[{warp}]'
        data = client.read_memory(0x80000000 + warp * 16, 16)
        result[f'{prefix}.pc'] = int.from_bytes(data[:4], 'little')
        result[f'{prefix}.active_mask'] = data[4]
        client.select_context(warp, 0)
        result[f'{prefix}.instructions_executed'] = word(0x80000114)
    registers = []
    for key in requested:
        match = re.fullmatch(r'warp\[(\d+)\]\.lane\[(\d+)\]\.R(\d+)', key)
        if match:
            registers.append((*map(int, match.groups()), key))
    selected = None
    for warp, lane, register, key in sorted(registers):
        if selected != (warp, lane):
            client.select_context(warp, lane)
            selected = (warp, lane)
        result[key] = client.read_register(register)
    return result


class GpuFpgaBackend:
    """Carga, ejecuta e inspecciona un caso GPU en la FPGA real."""

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
                f"Versión del backend GPU FPGA desconocida {version!r}; "
                f"opciones: {choices}"
            ) from error

        self.version = version
        self.monitor = _load_module(
            f"gpu_fpga_monitor_{version}_for_tests",
            repository / self.configuration["monitor_path"],
        )
        self.port = port
        self.serial_timeout = serial_timeout
        # Una sola comprobación por ejecución, antes de correr ningún caso.
        board.ensure_bitstream(
            self.monitor, port, serial_timeout,
            self.configuration["monitor_version"],
            repository / self.configuration["monitor_path"].parent,
            "gpu-fpga", version, upload_policy or board.UploadPolicy(),
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
    ) -> dict:
        # La FPGA se limita por timeout de pared, no por instrucciones.
        del max_instructions, register_numbers

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
            actual_version = client.get_version()
            expected_version = self.configuration["monitor_version"]
            actual_tuple = (actual_version.major, actual_version.minor)
            if actual_tuple != expected_version:
                expected_text = ".".join(map(str, expected_version))
                raise RuntimeError(
                    f"La FPGA conectada responde con monitor {actual_version}, "
                    f"pero --version gpu-fpga={self.version} requiere "
                    f"{expected_text}. Carga el bitstream correspondiente."
                )

            client.reset_cpu()
            client.write_memory(0, program)

            for address, data in initial_memory:
                client.write_memory(address, data)

            # configure_warps valida el JSON contra el modelo, exige la GPU
            # detenida y hace su propio reset antes de escribir PC, máscara y
            # workgroup de cada warp. Por eso va después de cargar el programa.
            client.configure_warps(warp_config)

            started = time.monotonic()
            client.run_cpu()
            deadline = started + timeout_seconds

            while True:
                status = client.get_status()
                if status.halted:
                    break
                if time.monotonic() >= deadline:
                    client.halt_cpu()
                    raise TimeoutError(
                        f"La GPU no terminó en {timeout_seconds:g} segundos"
                    )
                time.sleep(0.01)

            elapsed = time.monotonic() - started
            observations = read_observations(client, status, observation_fields or set())
            observations["duration_seconds"] = elapsed

            memory = {
                (address, size): client.read_memory(address, size)
                for address, size in memory_ranges
            }

        return {
            "halted": status.halted,
            "error": status.error,
            "error_code": status.error_code,
            "pc": status.pc,
            "registers": {},
            "observations": observations,
            "memory": memory,
        }
