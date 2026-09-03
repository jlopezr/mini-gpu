"""Backend de FPGA basado en el cliente del monitor UART."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType


DATA_MONITOR_BASE = 0x0010_0000


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FpgaBackend:
    """Carga, ejecuta e inspecciona un caso en la FPGA real."""

    def __init__(self, repository: Path, port: str, serial_timeout: float):
        self.monitor = _load_module(
            "fpga_monitor_for_tests",
            repository / "6.fpga-cpu" / "monitor.py",
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
    ) -> dict:
        del max_instructions  # La FPGA se limita mediante timeout de pared.

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
            client.reset_cpu()
            client.write_memory(0, program)

            for address, data in initial_memory:
                client.write_memory(DATA_MONITOR_BASE + address, data)

            client.run_cpu()
            deadline = time.monotonic() + timeout_seconds

            while True:
                status = client.get_status()
                if status.halted:
                    break
                if time.monotonic() >= deadline:
                    client.halt_cpu()
                    raise TimeoutError(
                        f"La CPU no terminó en {timeout_seconds:g} segundos"
                    )
                time.sleep(0.01)

            registers = {
                number: client.read_register(number)
                for number in sorted(register_numbers)
            }
            memory = {
                (address, size): client.read_memory(DATA_MONITOR_BASE + address, size)
                for address, size in memory_ranges
            }

        return {
            "halted": status.halted,
            "error": status.error,
            "error_code": status.error_code,
            "pc": status.pc,
            "registers": registers,
            "memory": memory,
        }
