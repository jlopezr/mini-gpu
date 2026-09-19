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


def _parameters_at_instantiation(prototype_dir: Path) -> dict | None:
    """Los parámetros con los que un top instancia `monitor`, si los pone.

    Desde que monitor.v es copia idéntica en la familia GPU, lo que hay DENTRO
    del fichero es el valor por DEFECTO, no el que se sintetiza: el de verdad lo
    pone quien lo instancia. Leer el localparam devolvía 2.4 para las cuatro
    cuando eran 2.5, 2.6, 2.6 y 2.6.
    """
    for path in sorted(prototype_dir.glob("*.v")):
        if path.name == "monitor.v":
            continue        # ahí el `#(` es la DECLARACIÓN, no una instancia
        if path.name.endswith("_tb.v"):
            # Un banco de pruebas instancia el monitor pero no es lo que se
            # sintetiza, y va antes que top.v por orden alfabético.
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"\bmonitor\s*#\(", text)
        if not match:
            continue
        depth, cursor = 1, match.end()
        while depth and cursor < len(text):
            depth += {"(": 1, ")": -1}.get(text[cursor], 0)
            cursor += 1
        lista = text[match.end():cursor]
        valores = dict(re.findall(r"\.(\w+)\(\s*8'([hd][0-9a-fA-F]+)\s*\)",
                                  lista))
        if "VERSION_MAJOR" in valores and "VERSION_MINOR" in valores:
            return valores
    return None


def _as_int(literal: str) -> int:
    """Un literal de 8 bits de Verilog, en la base que traiga."""
    return int(literal[1:], 16 if literal[0] == "h" else 10)


def monitor_version_from_rtl(prototype_dir: Path) -> tuple[int, int] | None:
    """La versión que la placa responde de verdad a GET_VERSION.

    Se mira primero la instanciación, porque es la que manda cuando monitor.v
    está parametrizado, y se cae al localparam para los prototipos que todavía
    lo llevan dentro (la familia CPU).

    Se admiten las dos bases de Verilog. Desde el renumerado el menor es el
    NÚMERO DE CARPETA, y escribirlo en decimal --`8'd16` en la 16-- es lo que
    hace que el valor se lea solo; en hexadecimal habría que poner `8'h10` para
    que la placa contestara «16», que es justo la clase de traducción mental que
    acaba en un número mal tecleado.
    """
    instancia = _parameters_at_instantiation(prototype_dir)
    if instancia is not None:
        return (_as_int(instancia["VERSION_MAJOR"]),
                _as_int(instancia["VERSION_MINOR"]))

    monitor_v = prototype_dir / "monitor.v"
    if not monitor_v.exists():
        return None
    text = monitor_v.read_text(encoding="utf-8", errors="replace")
    major = re.search(r"VERSION_MAJOR\s*=\s*8'([hd])([0-9a-fA-F]+)", text)
    minor = re.search(r"VERSION_MINOR\s*=\s*8'([hd])([0-9a-fA-F]+)", text)
    if not major or not minor:
        return None
    return (int(major.group(2), 16 if major.group(1) == "h" else 10),
            int(minor.group(2), 16 if minor.group(1) == "h" else 10))


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


def monitor_cycle_counters_from_rtl(prototype_dir: Path) -> bool:
    """CMD_GET_CYCLES (0x36) es el comando de monitor.v que da los contadores
    de ciclos/instrucciones; sin él no hay CPI que medir en esa placa.

    Se llamaba `perf_counters_from_rtl`, y el nombre colisionaba con la
    capacidad `perf_counters` de `capabilities.json`, que es otra cosa: el
    bloque MMIO de contadores de la 22 (`gpu_perf_counters.v`). No son
    sinónimos ni se solapan -- en la 22 esta función da False, porque su
    monitor tiene los 12 comandos base y no el 0x36, mientras que la capacidad
    sí está. Mismo nombre y valores opuestos para la misma carpeta.

    Esto mira el JUEGO DE COMANDOS DEL MONITOR; la capacidad mira el
    dispositivo. Ver docs/resumen-prototipos.md.
    """
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
