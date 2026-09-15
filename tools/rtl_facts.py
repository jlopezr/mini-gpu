"""Hechos leídos directamente de la carpeta de un prototipo, sin copiarlos a
mano en ningún sitio.

`monitor_version`, `clock_hz` y `capabilities` salen del RTL; `readme_title`
sale del primer encabezado de su README.md. `x.tests/backends/{fpga,
gpu_fpga}.py` y `tools/prototype_report.py` llaman a las mismas funciones, así
que un cambio en el RTL -- añadir una instrucción, subir el reloj -- o en el
README se refleja solo tocando ese fichero. Lo único que sigue siendo una
etiqueta elegida a mano es el alias corto (`ebr`, `alu`...) y, si el README no
basta, una descripción que lo sobreescriba -- ver `version.json` en cada
carpeta de prototipo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def readme_title(prototype_dir: Path) -> str:
    """Primer encabezado `# ...` de README.md, o cadena vacía si no hay uno.
    Es el valor por defecto de `description`: `version.json` solo hace falta
    cuando ese título no basta."""
    readme = prototype_dir / "README.md"
    if not readme.exists():
        return ""
    for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^#\s+(.*)", line)
        if match:
            return match.group(1).strip()
    return ""


def backend_from_rtl(prototype_dir: Path) -> str | None:
    """CPU o GPU no es una etiqueta: es qué módulo de núcleo hay en la carpeta."""
    if (prototype_dir / "cpu.v").exists():
        return "cpu"
    if (prototype_dir / "gpu_sm.v").exists() or (prototype_dir / "gpu_system.v").exists():
        return "gpu"
    return None


def monitor_version_from_rtl(prototype_dir: Path) -> tuple[int, int] | None:
    """VERSION_MAJOR/VERSION_MINOR son localparams reales en monitor.v: es lo
    que la placa responde de verdad a GET_VERSION, no una copia a mano."""
    monitor_v = prototype_dir / "monitor.v"
    if not monitor_v.exists():
        return None
    text = monitor_v.read_text(encoding="utf-8", errors="replace")
    major = re.search(r"VERSION_MAJOR\s*=\s*8'h([0-9a-fA-F]+)", text)
    minor = re.search(r"VERSION_MINOR\s*=\s*8'h([0-9a-fA-F]+)", text)
    if not major or not minor:
        return None
    return (int(major.group(1), 16), int(minor.group(1), 16))


def clock_hz_from_rtl(prototype_dir: Path) -> int | None:
    """FREQUENCY_PIN_CLKOP es el atributo que nextpnr usa de verdad para
    timing, en el fichero del PLL (su nombre varía: pll_120.v, pll_cpu.v...)."""
    for pll_file in sorted(prototype_dir.glob("pll*.v")):
        text = pll_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'FREQUENCY_PIN_CLKOP\s*=\s*"(\d+(?:\.\d+)?)"', text)
        if match:
            return int(float(match.group(1)) * 1_000_000)
    return None


def perf_counters_from_rtl(prototype_dir: Path) -> bool:
    """CMD_GET_CYCLES (0x36) es el comando de monitor.v que da los contadores
    de ciclos/instrucciones; sin él no hay CPI que medir en esa placa."""
    monitor_v = prototype_dir / "monitor.v"
    if not monitor_v.exists():
        return False
    text = monitor_v.read_text(encoding="utf-8", errors="replace")
    return re.search(r"CMD_GET_CYCLES\s*=\s*8'h36", text) is not None


def load_capability_signals(root: Path) -> dict:
    signals_path = root / "tools" / "capabilities.json"
    if not signals_path.exists():
        return {}
    data = json.loads(signals_path.read_text(encoding="utf-8"))
    return {name: spec for name, spec in data.items() if not name.startswith("_")}


def capabilities_from_rtl(prototype_dir: Path, signals: dict) -> tuple[str, ...]:
    found = []
    for name, spec in signals.items():
        # Sin `file` no hay nada que buscar en el RTL: es el caso de
        # `atomic_warp_faults`, que ningún hardware real implementa.
        file = spec.get("file")
        if file is None:
            continue
        target = prototype_dir / file
        if not target.exists():
            continue
        pattern = spec.get("pattern")
        if pattern is None or re.search(pattern, target.read_text(encoding="utf-8", errors="replace")):
            found.append(name)
    return tuple(found)
