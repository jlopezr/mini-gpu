"""Backend de MiniGPU en FPGA, sobre el cliente del monitor UART 2.0.

Es un backend propio y no una versión de `fpga.py` porque el runner lee
`ARCHITECTURE` del atributo de clase al construir `BACKEND_DEFINITIONS`, antes
de que exista una versión seleccionada: la arquitectura no puede depender de
`--version`. En este repositorio "versión" significa revisión de hardware de la
misma arquitectura (`ebr` y `sdram` son ambas CPU), igual que `simulator.py` y
`gpu_simulator.py` ya están separados por la misma razón.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType


VERSIONS = {
    "bram": {
        "monitor_path": Path("12.fpga-gpu/monitor.py"),
        "monitor_version": (2, 0),
        "description": "MiniGPU con 128 KiB de BRAM, 8 warps x 8 lanes",
    },
}
DEFAULT_VERSION = "bram"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class GpuFpgaBackend:
    """Carga, ejecuta e inspecciona un caso GPU en la FPGA real."""

    ARCHITECTURE = "gpu"

    def __init__(
        self,
        repository: Path,
        port: str,
        serial_timeout: float,
        version: str = DEFAULT_VERSION,
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

    def run(
        self,
        program: bytes,
        initial_memory: list[tuple[int, bytes]],
        register_numbers: set[int],
        memory_ranges: list[tuple[int, int]],
        max_instructions: int,
        timeout_seconds: float,
        warp_config: object,
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

            memory = {
                (address, size): client.read_memory(address, size)
                for address, size in memory_ranges
            }

        return {
            "halted": status.halted,
            "error": status.error,
            "error_code": status.error_code,
            "pc": status.pc,
            # Los registros por warp y lane exigirían 2048 lecturas UART y una
            # conmutación de contexto por lane. Este backend no publica esas
            # observaciones: los casos que fijen `expect.warps` no son
            # ejecutables aquí todavía.
            "registers": {},
            "observations": {
                "duration_seconds": elapsed,
            },
            "memory": memory,
        }
