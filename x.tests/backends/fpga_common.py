"""Lo que comparten los backends de placa: `fpga_cpu`, `fpga_gpu` y `fpga_sys`.

Los tres descubren sus versiones de las carpetas de prototipo (`version.json`),
comprueban el bitstream una vez, abren el puerto por caso y verifican la versión
del monitor. Lo que cambia es qué carpetas cuentan, qué se lanza y qué se observa.
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Callable

from . import board, frame_capture
from .common import expand_for, load_module, missing_capabilities

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from tools.rtl_facts import (  # noqa: E402 (necesita REPOSITORY en sys.path)
    clock_hz_from_rtl,
    load_capability_signals,
    monitor_version_from_rtl,
    readme_title,
)


def prototype_number(directory: Path) -> int:
    match = re.match(r"(\d+)", directory.name)
    return int(match.group(1)) if match else 0


def build_versions(
    select: Callable[[Path], bool],
    capabilities: Callable[[Path, dict], tuple],
    extra: Callable[[Path, dict], None] | None = None,
) -> dict:
    """Las versiones de un backend, leídas de las carpetas de prototipo.

    Cada versión es una carpeta con un `version.json` (`{"alias": ...}`, y
    opcionalmente `"description"` si el título del README no basta); eso es lo
    único que se elige a mano. `monitor_version`, `capabilities`, `clock_hz` y la
    descripción por defecto se leen de esa carpeta con las funciones de
    `tools/rtl_facts.py`, las mismas que usa `tools/prototype_report.py`.

    Un `cpu.v`/`monitor.v` sin `version.json` NO cuenta: es la señal de «esto es
    un target de test soportado», no solo «hay RTL sintetizable ahí».
    `17.fpga-gpu-ram-v2` tiene ambos y no es un target: es un camino crítico
    alternativo de la 14.

    `select(directory)` dice si la carpeta es de este backend,
    `capabilities(directory, signals)` devuelve sus capacidades y
    `extra(directory, entry)` puede añadir campos propios a la entrada.
    """
    signals = load_capability_signals(REPOSITORY)
    manifests = sorted(
        REPOSITORY.glob("*/version.json"), key=lambda p: prototype_number(p.parent)
    )
    versions = {}
    for manifest_path in manifests:
        directory = manifest_path.parent
        if not select(directory):
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        monitor_version = monitor_version_from_rtl(directory)
        if monitor_version is None:
            raise RuntimeError(
                f"no se pudo leer VERSION_MAJOR/VERSION_MINOR de "
                f"{directory / 'monitor.v'}"
            )
        entry = {
            "monitor_path": directory.relative_to(REPOSITORY) / "monitor.py",
            "monitor_version": monitor_version,
            "description": manifest.get("description") or readme_title(directory),
            "capabilities": capabilities(directory, signals),
        }
        clock_hz = clock_hz_from_rtl(directory)
        if clock_hz is not None:
            entry["clock_hz"] = clock_hz
        if extra is not None:
            extra(directory, entry)
        versions[manifest["alias"]] = entry
    return versions


def missing_with_hint(case: dict, versions: dict, version: str) -> str | None:
    """«sin X (la tienen: ...)» si al caso le falta algo, o None.

    El motivo dice qué versión sí lo tiene, que es lo que uno quiere saber
    cuando ve el SKIP. La que falla ya sale en el prefijo `[version]` del SKIP.
    """
    available = expand_for(versions[version]["capabilities"])
    missing = missing_capabilities(case, available)
    if not missing:
        return None
    having_it = sorted(
        name for name, config in versions.items()
        if set(missing) <= expand_for(config["capabilities"])
    )
    hint = f" (la tienen: {', '.join(having_it)})" if having_it else ""
    return f"sin {', '.join(missing)}{hint}"


def region_reason(case: dict, versions: dict, version: str, backend_name: str):
    """Por qué el caso no cabe en el mapa de la versión, o None.

    El mapa lo declara el `monitor.py` de cada versión, que es quien lo
    implementa; aquí solo se lee su constante, sin abrir el puerto.
    """
    monitor = load_module(
        f"{backend_name.replace('-', '_')}_monitor_{version}_for_regions",
        REPOSITORY / versions[version]["monitor_path"],
    )
    return board.region_incompatibility(case, monitor.ARCHITECTURAL_REGIONS)


def architectural_size(monitor: ModuleType) -> int:
    """Tamaño del espacio arquitectónico que declara un monitor."""
    return max(end for _, end in monitor.ARCHITECTURAL_REGIONS)


def write_register(client, address: int, value: int) -> None:
    """Byte a byte, no por bloque.

    Los registros de vídeo no son memoria: viven fuera de las regiones que
    `write_memory` valida, y el monitor solo los atiende con WRITE_BYTE. Por
    bloque el cliente lo rechaza antes de enviar nada.
    """
    for offset, byte in enumerate(value.to_bytes(4, "little")):
        client.write_byte(address + offset, byte)


class MonitorBackend:
    """Un backend que habla con la placa por el monitor UART.

    Cada subclase fija `ARCHITECTURE`, `NAME` (el de `--backend`), `VERSIONS` y
    `DEFAULT_VERSION`, e implementa `_run_una_vez`.
    """

    ARCHITECTURE: str
    NAME: str
    VERSIONS: dict
    DEFAULT_VERSION: str

    def __init__(
        self,
        repository: Path,
        port: str,
        serial_timeout: float,
        version: str | None = None,
        upload_policy: board.UploadPolicy | None = None,
    ):
        version = self.DEFAULT_VERSION if version is None else version
        try:
            self.configuration = self.VERSIONS[version]
        except KeyError as error:
            choices = ", ".join(sorted(self.VERSIONS))
            raise ValueError(
                f"Versión del backend {self.NAME} desconocida {version!r}; "
                f"opciones: {choices}"
            ) from error

        self.version = version
        self.monitor = load_module(
            f"{self.NAME.replace('-', '_')}_monitor_{version}_for_tests",
            repository / self.configuration["monitor_path"],
        )
        self.port = port
        self.serial_timeout = serial_timeout
        # Una sola comprobación por ejecución, antes de correr ningún caso.
        board.ensure_bitstream(
            self.monitor, port, serial_timeout,
            self.configuration["monitor_version"],
            repository / self.configuration["monitor_path"].parent,
            self.NAME, version, upload_policy or board.UploadPolicy(),
        )

    @contextmanager
    def connect(self):
        """Abre el puerto y devuelve el cliente, con la versión del monitor ya verificada."""
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
            expected = self.configuration["monitor_version"]
            if (actual.major, actual.minor) != expected:
                raise RuntimeError(
                    f"La FPGA conectada responde con monitor {actual}, "
                    f"pero --version {self.NAME}={self.version} requiere "
                    f"{'.'.join(map(str, expected))}. Carga el bitstream "
                    "correspondiente."
                )
            yield client

    def run(self, *args, **kwargs) -> dict:
        # Si la parada por intercambios sale imprecisa, el caso se repite: ver
        # `frame_capture`. Sin `run_until` no hay parada que pueda serlo.
        return frame_capture.with_retries(lambda: self._run_once(*args, **kwargs))

    def _run_once(self, *args, **kwargs) -> dict:
        raise NotImplementedError
