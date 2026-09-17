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
    """Reloj al que corre el núcleo del prototipo.

    Primero, `FREQUENCY_PIN_CLKOP` en el fichero del PLL (su nombre varía:
    pll_120.v, pll_cpu.v...): es el atributo que nextpnr usa de verdad para
    timing. Los cores de CPU lo tienen porque suben el reloj a 80/100/120 MHz.

    Si no hay PLL, el reloj es el oscilador de la placa, y se lee del nombre
    del puerto de entrada del top (`input clk_25mhz`). Las GPU están en ese
    caso: 12, 14 y 17 no tienen PLL, y el de la 22 es solo para los relojes de
    pixel de HDMI -- la GPU, el monitor, la UART y la SDRAM van en `clk_25mhz`.
    Devolver None ahí diría "no se sabe" cuando el valor está bien definido.
    Los dominios de pixel no salen aquí: están desglosados, con su fmax, en
    `docs/synthesis-report.md`.
    """
    for pll_file in sorted(prototype_dir.glob("pll*.v")):
        text = pll_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'FREQUENCY_PIN_CLKOP\s*=\s*"(\d+(?:\.\d+)?)"', text)
        if match:
            return int(float(match.group(1)) * 1_000_000)
    for top_file in sorted(prototype_dir.glob("top*.v")):
        text = top_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"input\s+(?:wire\s+)?clk_(\d+)mhz\b", text)
        if match:
            return int(match.group(1)) * 1_000_000
    return None


def uart_baud_from_rtl(prototype_dir: Path) -> int | None:
    """Baudio de la UART del monitor: reloj del sistema entre el divisor.

    El divisor es un `localparam UART_DIVISOR`/`UART_CLOCKS_PER_BIT` del top,
    y es una constante elegida, no una división: tiene que ser múltiplo de 4
    --`uart.v` lo comprueba en elaboración-- y dar un baudio que el FTDI genere
    exacto. Por eso se lee en vez de calcularse desde un baudio objetivo.
    """
    clock_hz = clock_hz_from_rtl(prototype_dir)
    if clock_hz is None:
        return None
    for top_file in sorted(prototype_dir.glob("top*.v")):
        text = top_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(
            r"localparam\s+(?:integer\s+)?UART_(?:DIVISOR|CLOCKS_PER_BIT)\s*=\s*([0-9_]+)\s*;",
            text,
        )
        if match:
            divisor = int(match.group(1).replace("_", ""))
            if divisor:
                return clock_hz // divisor
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


def capability_files(spec: dict) -> tuple[str, ...]:
    """Los ficheros donde puede estar la señal de una capacidad.

    `file` admite un nombre o una lista de alternativas, y la lista no es un
    lujo: un mismo dispositivo se llama distinto en cada familia --el vídeo es
    `video_registers.v` en CPU y `gpu_video_regs.v` en GPU-- y sin alternativas
    haría falta una capacidad por familia, que es justo lo que impide compartir
    un caso de prueba entre prototipos.
    """
    file = spec.get("file")
    if file is None:
        return ()
    if isinstance(file, str):
        return (file,)
    return tuple(file)


def capability_architectures(spec: dict) -> tuple[str, ...]:
    """`architecture` admite un valor o una lista, por lo mismo que `file`: hay
    dispositivos que tienen las dos familias."""
    architecture = spec["architecture"]
    if isinstance(architecture, str):
        return (architecture,)
    return tuple(architecture)


def capabilities_from_rtl(prototype_dir: Path, signals: dict) -> tuple[str, ...]:
    found = []
    for name, spec in signals.items():
        # Sin `file` no hay nada que buscar en el RTL: es el caso de
        # `atomic_warp_faults`, que ningún hardware real implementa.
        for file in capability_files(spec):
            target = prototype_dir / file
            if not target.exists():
                continue
            pattern = spec.get("pattern")
            if pattern is None or re.search(pattern, target.read_text(encoding="utf-8", errors="replace")):
                found.append(name)
                break
    return tuple(found)
