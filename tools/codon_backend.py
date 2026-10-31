"""Compilación, caché y lanzamiento del motor Codon de `sim-sys --backend codon`.

El motor compila los núcleos de los simuladores **sin cambiarlos**: se copian tal
cual a `_build/codon-engine/<hash>/src/`, junto a los gemelos `.codon` de lo que
se queda en Python (periféricos, traza, perfil, desensamblador) y a
`tools/codon/engine.codon`. Codon prefiere `X.codon` a `X.py`, así que no hace
falta excluir los `.py`; y hay que copiar, no enlazar: Codon sigue los enlaces y
busca los imports desde el fichero real (tools/codon/LIMITACIONES.md).
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

from tools.sim_host import gui_python

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "tools/codon"

#: Destino en el directorio de compilación -> fuente en el repositorio.
SOURCES = {
    "engine.codon": "tools/codon/engine.codon",
    "minicpu_core.py": "2.cpu-sim-func/minicpu_core.py",
    "minigpu_core.py": "11.gpu-sim-func/minigpu_core.py",
    "cpu_gpu_core.py": "32.cpu-gpu-func-sim/cpu_gpu_core.py",
    "gpu_trace.codon": "11.gpu-sim-func/gpu_trace.codon",
    "minigpu_isa.codon": "1.isa/asm2/minigpu_isa.codon",
    "tools/__init__.py": "tools/__init__.py",
    "tools/codon_compat.codon": "tools/codon_compat.codon",
    "tools/mmio_device.py": "tools/mmio_device.py",
    "tools/mmio_map.py": "tools/mmio_map.py",
    "tools/sim_devices.codon": "tools/sim_devices.codon",
    "tools/sim_profile.codon": "tools/sim_profile.codon",
    "tools/sysid_device.py": "tools/sysid_device.py",
}


def compiler() -> str:
    path = (os.environ.get("MINIGPU_CODON") or shutil.which("codon")
            or str(ROOT / "_build/codon-sdk/bin/codon"))
    if not Path(path).is_file():
        raise ValueError("no se encontró Codon; usa MINIGPU_CODON=/ruta/a/codon")
    return str(Path(path).resolve())


def library() -> str:
    """La libpython de CPython con la que el motor usa los periféricos.

    `CODON_PYTHON` manda. Si no, la del CPython que corre; desde PyPy, la del
    Python de las ventanas (`gui_python`), que es CPython.
    """
    configured = os.environ.get("CODON_PYTHON")
    if configured:
        return configured
    script = ("import sys, sysconfig; from pathlib import Path; "
              "c = [Path(sys.base_prefix) / 'Python', "
              "Path(sysconfig.get_config_var('LIBDIR') or '') / str(sysconfig.get_config_var('LDLIBRARY'))]; "
              "print(next((str(p) for p in c if p.is_file()), ''))")
    if sys.implementation.name == "cpython":
        candidates = [Path(sys.base_prefix) / "Python",
                      Path(sysconfig.get_config_var("LIBDIR") or "")
                      / str(sysconfig.get_config_var("LDLIBRARY"))]
        path = next((str(p) for p in candidates if p.is_file()), "")
    else:
        path = subprocess.check_output([gui_python(), "-c", script], text=True).strip()
    if not path:
        raise ValueError("falta libpython de CPython; configura CODON_PYTHON")
    return path


def prepare() -> tuple[Path, dict]:
    """El ejecutable del motor (compilándolo si sus fuentes han cambiado) y su entorno."""
    codon = compiler()
    lib = library()
    version = subprocess.check_output([codon, "--version"], text=True).strip()
    digest = hashlib.sha256(f"{version}\n{codon}\n{lib}\n".encode())
    for target, source in sorted(SOURCES.items()):
        digest.update(target.encode())
        digest.update((ROOT / source).read_bytes())
    output = ROOT / "_build/codon-engine" / digest.hexdigest()[:20]
    binary = output / "sim-sys-codon"
    # Dentro del motor, sys.executable es el propio binario: las ventanas
    # necesitan un Python de verdad (MINIGPU_CODON_GUI_PYTHON, ver host.py).
    env = dict(os.environ, CODON_PYTHON=lib, MINIGPU_CODON_GUI_PYTHON=gui_python(),
               PYTHONPATH=os.pathsep.join((str(HOST), str(ROOT))))
    if not binary.exists():
        src = output / "src"
        shutil.rmtree(src, ignore_errors=True)
        for target, source in SOURCES.items():
            (src / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, src / target)
        print("Codon: compilando motor CPU+GPU (queda en caché)", file=sys.stderr, flush=True)
        proc = subprocess.run([codon, "build", "-release", "-o", str(binary), str(src / "engine.codon")],
                              env=env, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError("falló la compilación:\n" + proc.stdout + proc.stderr)
    return binary, env


def run_cli(argv: list[str]) -> int:
    binary, env = prepare()
    return subprocess.call([str(binary), *argv], env=env)


#: Lo que no es estado de la simulación (enlaces a otros objetos, la RAM, los
#: ganchos de traza y perfil, la contabilidad de `run` y del reloj por lotes):
#: `snapshot` lo omite.
_LINKS = {"memory", "bus", "hooks", "video", "serial", "input", "sysid", "system",
          "cpu", "gpu", "streaming_multiprocessor", "warps", "processors",
          "trace", "trace_stream", "trace_limit", "trace_lines", "profile",
          "_cpu_limit", "_gpu_limit", "_limit_slack", "_batching", "_ticks_pending", "_ticks_quiet",
          "_serial_wait", "_input_wait", "_video_wait"}
#: En las lanes de la GPU, además, el resultado de la última `evaluate`, que el
#: warp ya ha confirmado.
_LANE_SCRATCH = {"rd", "value", "next_pc", "halted", "store_size", "store_address",
                 "store_value"}


def _fields(obj, skip: set[str] = _LINKS) -> dict:
    return {k: v for k, v in vars(obj).items() if k not in skip}


def _plain(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"no serializable: {type(value).__name__}")


def snapshot(system) -> dict:
    """Todo el estado de un `CpuGpuSystem`, comparable entre los dos motores.

    Recorre los campos de cada objeto (`vars`), no una lista: el espejo Python
    del motor Codon solo recibe lo que copia `engine.codon:export`, y si falta
    algo esta comparación lo ve. La RAM va resumida con SHA-256.
    """
    gpu = system.gpu
    sm = gpu.system.streaming_multiprocessor
    result = {
        "system": _fields(system), "cpu": _fields(system.cpu), "gpu": _fields(gpu),
        "gpu.system": _fields(gpu.system), "sm": _fields(sm),
        "warps": [_fields(w) for w in sm.warps],
        "lanes": [[_fields(lane, _LINKS | _LANE_SCRATCH) for lane in w.processors]
                  for w in sm.warps],
        "ram": hashlib.sha256(system.memory).hexdigest(),
    }
    if system.video is not None:
        result["video"] = dict(vars(system.video))
    if system.input is not None:
        device = system.input
        result["input"] = {k: v for k, v in vars(device).items() if k not in ("host", "script")}
        result["input"]["script_remaining"] = len(device.script)
    if system.serial is not None:
        result["serial"] = {k: v for k, v in vars(system.serial).items() if k != "tty"}
    return json.loads(json.dumps(result, default=_plain))
