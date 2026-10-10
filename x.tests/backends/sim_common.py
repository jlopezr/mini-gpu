"""Lo que comparten los backends de simulador: `sim_cpu`, `sim_gpu` y `sim_sys`.

Los tres cargan un simulador de otra carpeta, le cuelgan los mismos periféricos
(vídeo, serie, entrada), cargan la memoria inicial y devuelven un diccionario con
la misma forma. Lo que cambia es la máquina y qué se observa de ella.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.sim_peripherals import video_result  # noqa: E402,F401  (se reexporta)


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def expand_for(names) -> frozenset:
    """Expande las capacidades implicadas.

    El import va dentro para no crear una dependencia circular: `run_tests`
    importa los backends al arrancar.
    """
    from run_tests import expand_capabilities

    return expand_capabilities(names)


def capabilities_of(versions: dict, version: str) -> frozenset:
    """Lo que tiene una versión de simulador, con las implicaciones ya expandidas."""
    return expand_for(versions[version]["capabilities"])


def missing_capabilities(case: dict, available: frozenset) -> list[str]:
    """Las capacidades que el caso pide y el simulador no declara."""
    return [name for name in case.get("requires", []) if name not in available]


def input_device(script: str | None):
    """El INPUT de un caso, o None si no declara `input`.

    El guion tiene que conectar lo que use: aquí no hay `--keyboard` ni
    `--mouse`, así que un caso describe el comportamiento entero.
    """
    if script is None:
        return None
    from tools import input_script
    from tools.sim_devices import InputDevice

    device = InputDevice()
    actions = input_script.parse(script)
    input_script.check(actions)
    device.attach_script(actions)
    return device


def make_video(module: ModuleType, video: dict | None, what: str):
    """El VideoDevice de un caso, o None si no pide vídeo.

    Las bases arrancan a cero, como el hardware, y ahí se quedan: el framebuffer
    lo elige el PROGRAMA, no el arnés.

    `run_until: {swap: N}` es una parada del arnés, NO por HALT_AT: es una
    condición de observación del banco de pruebas --captura el frame tras el
    intercambio N-- y no un registro que el programa vea. Armar HALT_AT, además
    de HALT_TARGET, sería escribir en el dispositivo del programa.
    """
    if video is None:
        return None
    video_class = getattr(module, "VideoDevice", None)
    if video_class is None:
        raise RuntimeError(f"{what} no tiene VideoDevice")
    dispositivo = video_class()
    if video.get("run_until_swap"):
        dispositivo.stop_after_swaps = video["run_until_swap"]
    return dispositivo


def make_serial(module: ModuleType, stdin: bytes, what: str):
    """El puerto serie de un caso.

    Se construye SIEMPRE que el simulador lo tenga, aunque `stdin` esté vacío: un
    programa puede escribir sin haber leído nada.
    """
    serial_class = getattr(module, "SerialDevice", None)
    if serial_class is None:
        if stdin:
            raise RuntimeError(f"{what} no tiene SerialDevice")
        return None
    serie = serial_class(stdin=stdin)
    serie.attach_host()
    return serie


def load_initial_memory(memory: bytearray, initial_memory: list[tuple[int, bytes]]) -> None:
    for address, data in initial_memory:
        end = address + len(data)
        if address < 0 or end > len(memory):
            raise ValueError(f"Inicialización fuera de memoria: 0x{address:08x}")
        memory[address:end] = data
