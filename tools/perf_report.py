#!/usr/bin/env python3
"""Informe de rendimiento de todos los prototipos, a partir de las medidas archivadas.

Lee `<prototipo>/reports/*/measure.json` (las que escribe `run_tests.py --measure`)
y produce un Markdown con una tabla por magnitud --tiempo, CPI, FPS-- donde cada
fila es un programa y cada columna un prototipo, mas la evolucion de cada
prototipo entre medidas: para ver si vamos a mejor o a peor.

No toca la placa ni mide nada: solo lee lo ya archivado. Para medir, `bench-all`.

  perf-report                         informe con la medida mas reciente de cada prototipo
  perf-report --label bench           solo medidas con esa etiqueta
  perf-report --history 8             evolucion de las ultimas 8 medidas
  perf-report -o informe.md           fichero de salida (por defecto reports/rendimiento/)

Tres advertencias que el informe repite donde hacen falta:

- Un programa de video, o que espera bytes de la UART, SINCRONIZA con algo real
  (vsync, baudrate): su tiempo y su numero de instrucciones dependen de eso y no
  solo del diseno. Se marcan con `*` y no entran en el CPI del conjunto.
- FPS = intercambios por segundo de reloj de la placa (swaps * f / ciclos). Con
  vsync a 60 Hz no pasa de 60: si llega, el programa va sobrado y la cifra mide
  el monitor, no el diseno.
- Los ciclos de GPU son por instruccion de WARP, no por instruccion de hilo.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.measure_archive import MEASURE_JSON, load_measure, ns_per_instruction  # noqa: E402
from tools.rtl_facts import backend_from_rtl  # noqa: E402

VSYNC_HZ = 60.0
FAMILIES = (("cpu", "CPU"), ("gpu", "GPU"))


def _number(directory: Path) -> int:
    match = re.match(r"(\d+)", directory.name)
    return int(match.group(1)) if match else 0


def _short(directory: Path) -> str:
    """`21.fpga-cpu-hdmi-alu` -> `21`: las columnas se leen mejor cortas."""
    return str(_number(directory))


def collect(root: Path, label: str | None):
    """`{familia: [(directorio, [medidas de la mas nueva a la mas vieja])]}`."""
    found: dict[str, list] = {"cpu": [], "gpu": []}
    for directory in sorted((p for p in root.iterdir() if p.is_dir()), key=_number):
        reports = directory / "reports"
        if not reports.is_dir():
            continue
        family = backend_from_rtl(directory)
        if family not in found:
            continue
        measures = []
        for path in sorted(reports.glob(f"*/{MEASURE_JSON}"), reverse=True):
            try:
                document = load_measure(path)
            except (OSError, ValueError):
                continue
            if label and document.get("label") != label:
                continue
            document["_folder"] = path.parent.name
            measures.append(document)
        if measures:
            # Cada prototipo se mira con lo MAS RECIENTE de cada caso, no con una
            # sola medida: una corrida parcial (unas demos, un solo directorio)
            # no puede dejar en blanco lo que se midio antes.
            merged = {}
            for document in measures:
                for name, data in document.get("cases", {}).items():
                    merged.setdefault(name, data)
            measures[0] = dict(measures[0], cases=merged)
            found[family].append((directory, measures))
    return found


def _cases(document):
    return {name: data for name, data in document.get("cases", {}).items()}


def _clock_hz(document):
    for data in document.get("cases", {}).values():
        if data.get("clock_hz"):
            return data["clock_hz"]
    return None


def _ms(data):
    if not data or data.get("skipped") or data.get("cycles") is None or not data.get("clock_hz"):
        return None
    return 1000.0 * data["cycles"] / data["clock_hz"]


def _cpi(data):
    if not data or data.get("skipped") or not data.get("instructions") or data.get("cycles") is None:
        return None
    return data["cycles"] / data["instructions"]


MIN_SWAPS_FOR_FPS = 10


def _fps(data):
    """Intercambios por segundo de reloj de la placa, o None si no hay con que.

    Menos de `MIN_SWAPS_FOR_FPS` intercambios no da una cifra: arrancar, dibujar
    el primer frame y esperar al primer vsync pesan mas que el ritmo, y salian
    1542 FPS con un solo swap. Es el mismo corte que usa el runner (`--measure`)
    para su `~FPS`."""
    if not data or data.get("skipped"):
        return None
    video, cycles, clock = data.get("video"), data.get("cycles"), data.get("clock_hz")
    if not video or (video.get("swaps") or 0) < MIN_SWAPS_FOR_FPS or cycles is None or not clock:
        return None
    return video["swaps"] * clock / cycles


def _cell(data, value, fmt):
    if data is None:
        return "—"
    if data.get("skipped"):
        return "n/a"
    return "sin contadores" if value is None else fmt.format(value)


def _row(cells):
    return "| " + " | ".join(cells) + " |"


def _table(header, rows):
    lines = [_row(header), _row(["---"] + ["---:"] * (len(header) - 1))]
    lines += [_row(r) for r in rows]
    return lines


def _program_names(entries):
    names = []
    for _directory, measures in entries:
        for name in _cases(measures[0]):
            if name not in names:
                names.append(name)
    return sorted(names)


def _is_realtime(entries, name):
    return any(_cases(m[0]).get(name, {}).get("realtime") for _d, m in entries)


def common_cpi(entries):
    """CPI de cada prototipo sobre los casos que TODOS midieron y no son de tiempo real.

    Comparar el CPI global de cada uno no vale: cada prototipo admite casos
    distintos (el de menos capacidades se salta los que usan extensiones), y un
    conjunto distinto da un promedio distinto aunque el diseno fuera igual."""
    def usable(data):
        return (data and not data.get("skipped") and not data.get("realtime")
                and data.get("instructions") and data.get("cycles") is not None)
    # Solo cuentan los prototipos que MIDEN ciclos. Los que no tienen contadores
    # (6, 10, 12, 14) tienen un conjunto vacio, y meterlos en la interseccion
    # dejaba a todos sin casos comunes: el CPI salia `n/d` para el resto.
    sets = [{n for n, d in _cases(m[0]).items() if usable(d)} for _d, m in entries]
    with_counters = [s for s in sets if s]
    names = set.intersection(*with_counters) if with_counters else set()
    result = []
    for (_directory, measures), mine in zip(entries, sets):
        cases = _cases(measures[0])
        cycles = sum(cases[n]["cycles"] for n in names) if mine else 0
        instructions = sum(cases[n]["instructions"] for n in names) if mine else 0
        result.append(cycles / instructions if instructions else None)
    return result, len(names)


def summary_table(entries):
    rows = []
    cpis, common = common_cpi(entries)
    for (directory, measures), common_value in zip(entries, cpis):
        latest = measures[0]
        fmax = latest.get("fmax") or {}
        cpi, ns = common_value, ns_per_instruction(common_value, latest.get("fmax"))
        clock = _clock_hz(latest)
        measured = sum(1 for d in _cases(latest).values()
                       if not d.get("skipped") and d.get("cycles") is not None)
        skipped = sum(1 for d in _cases(latest).values() if d.get("skipped"))
        rows.append([
            f"{_short(directory)} {latest.get('version', '')}",
            "n/d" if clock is None else f"{clock / 1e6:g} MHz",
            f"{fmax['achieved_mhz']:.1f} MHz" if fmax.get("achieved_mhz") else "n/d",
            "n/d" if cpi is None else f"{cpi:.2f}",
            "n/d" if ns is None else f"{ns:.1f}",
            f"{measured} medidos, {skipped} omitidos",
            f"{latest.get('created', '')[:16].replace('T', ' ')} ({latest.get('label')})",
        ])
    return _table(["Prototipo", "Reloj", "Fmax", f"CPI ({common} comunes)", "ns/instr a Fmax",
                   "Casos", "Medida"], rows), common


def per_program_table(entries, value, fmt, title_note=""):
    names = _program_names(entries)
    header = ["Programa"] + [f"{_short(d)} {m[0].get('version', '')}" for d, m in entries]
    rows = []
    for name in names:
        mark = "\\*" if _is_realtime(entries, name) else ""
        rows.append([name + mark] + [
            _cell(_cases(m[0]).get(name), value(_cases(m[0]).get(name)), fmt)
            if name in _cases(m[0]) else "—"
            for _d, m in entries])
    return _table(header, rows)


def video_table(entries):
    names = [n for n in _program_names(entries)
             if any(_cases(m[0]).get(n, {}).get("video") for _d, m in entries)]
    if not names:
        return None
    header = ["Programa"] + [f"{_short(d)} {m[0].get('version', '')}" for d, m in entries]
    rows = []
    for name in names:
        row = [name]
        for _d, m in entries:
            data = _cases(m[0]).get(name)
            fps = _fps(data)
            if data is None:
                row.append("—")
            elif data.get("skipped"):
                row.append("n/a")
            elif fps is None:
                swaps = (data.get("video") or {}).get("swaps")
                row.append("corto" if swaps is not None and data.get("cycles") is not None
                           else "sin contadores")
            else:
                row.append(f"{fps:.1f}" + (" (vsync)" if fps >= VSYNC_HZ - 1 else ""))
        rows.append(row)
    return _table(header, rows)


def _delta(before, after):
    if before is None or after is None or before == 0:
        return None
    return 100.0 * (after - before) / before


def _common_change(document, previous):
    """`(cambio %, casos comunes)` del CPI entre dos medidas, sobre los casos que
    las dos tienen. Comparar el CPI global de cada una no vale: una pasada
    parcial (unas demos) y una completa promedian conjuntos distintos, y
    salia un `-56 %` que era solo el reparto de casos."""
    def usable(data):
        return (data and not data.get("skipped") and not data.get("realtime")
                and data.get("instructions") and data.get("cycles") is not None)
    now, before = _cases(document), _cases(previous)
    names = [n for n in now if usable(now[n]) and usable(before.get(n))]
    if not names:
        return None, 0
    def pooled(cases):
        return (sum(cases[n]["cycles"] for n in names)
                / sum(cases[n]["instructions"] for n in names))
    return _delta(pooled(before), pooled(now)), len(names)


def history_table(entries, depth):
    rows = []
    for directory, measures in entries:
        for index, document in enumerate(measures[:depth]):
            cpi = document.get("cpi")
            ns = ns_per_instruction(cpi, document.get("fmax"))
            previous = measures[index + 1] if index + 1 < len(measures) else None
            change, common = _common_change(document, previous) if previous else (None, 0)
            same_rtl = previous is not None and previous.get("source_sha256") == document.get("source_sha256")
            note = ""
            if change is not None:
                note = f"{change:+.1f} % ({common} casos" + (", mismo RTL)" if same_rtl else ")")
            rows.append([
                f"{_short(directory)} {document.get('version', '')}",
                document.get("created", "")[:16].replace("T", " "),
                str(document.get("label")),
                "n/d" if cpi is None else f"{cpi:.2f}",
                "n/d" if ns is None else f"{ns:.1f}",
                note or "—",
            ])
    return _table(["Prototipo", "Fecha", "Etiqueta", "CPI (su conjunto)", "ns/instr",
                   "CPI vs anterior (casos comunes)"], rows)


MIN_INSTRUCTIONS_FOR_CHANGE = 1000


def changes_table(entries, threshold=1.0):
    """Casos cuyo CPI cambio al menos `threshold` % respecto a la medida anterior.

    Los casos de menos de `MIN_INSTRUCTIONS_FOR_CHANGE` instrucciones no se
    juzgan: con 8 instrucciones, unos pocos ciclos de arranque o de sondeo son
    un +30 % que no dice nada del diseno, y salia marcado como `peor`. Se
    cuentan aparte para que no desaparezcan sin decirlo."""
    rows = []
    breves = 0
    for directory, measures in entries:
        if len(measures) < 2:
            continue
        now, before = _cases(measures[0]), _cases(measures[1])
        for name in sorted(now):
            if now[name].get("realtime") or name not in before:
                continue
            change = _delta(_cpi(before[name]), _cpi(now[name]))
            if change is None or abs(change) < threshold:
                continue
            if min(now[name].get("instructions") or 0,
                   before[name].get("instructions") or 0) < MIN_INSTRUCTIONS_FOR_CHANGE:
                breves += 1
                continue
            rows.append([f"{_short(directory)} {measures[0].get('version', '')}", name,
                         f"{_cpi(before[name]):.2f}", f"{_cpi(now[name]):.2f}",
                         f"{change:+.1f} %", "peor" if change > 0 else "mejor"])
    if not rows:
        return None
    lines = _table(["Prototipo", "Programa", "CPI antes", "CPI ahora", "Cambio", ""], rows)
    if breves:
        lines += ["", f"No se juzgan {breves} caso(s) de menos de {MIN_INSTRUCTIONS_FOR_CHANGE} "
                  "instrucciones: unos pocos ciclos de arranque cambian su CPI mas que cualquier "
                  "cambio de diseno."]
    return lines


def build_report(root: Path, label: str | None, history: int) -> str:
    found = collect(root, label)
    out = ["# Informe de rendimiento", "",
           f"Generado el {datetime.now():%Y-%m-%d %H:%M} con la medida mas reciente de cada "
           f"prototipo{f' (etiqueta `{label}`)' if label else ''}.", "",
           "Leyendas: `*` el programa sincroniza con video o UART, y su tiempo depende de eso; "
           "`n/a` el prototipo no admite el caso; `sin contadores` el RTL no tiene el bloque "
           "de rendimiento; `—` no se midio.", ""]
    if not any(found.values()):
        out += ["**No hay medidas archivadas.** Genera algunas con `bench-all`.", ""]
        return "\n".join(out)
    for key, title in FAMILIES:
        entries = found[key]
        if not entries:
            continue
        unit = "instruccion de warp" if key == "gpu" else "instruccion"
        out += [f"## {title}", "", "### Resumen por prototipo", ""]
        summary, common = summary_table(entries)
        out += summary
        out += ["", f"`CPI` es ciclos por {unit}, sobre los {common} casos que TODOS los prototipos "
                "de la tabla midieron y no son de tiempo real. "
                "`ns/instr a Fmax` es una PROYECCION a la frecuencia maxima que alcanzo el build "
                "(CPI / Fmax), no una medida: el reloj real es el de la columna Reloj.", ""]
        out += ["### Tiempo de ejecucion (ms)", ""]
        out += per_program_table(entries, _ms, "{:.3f}")
        out += ["", f"### Ciclos por {unit}", ""]
        out += per_program_table(entries, _cpi, "{:.2f}")
        video = video_table(entries)
        if video:
            out += ["", "### Video: FPS", ""] + video
            out += ["", f"Intercambios por segundo de la placa. Con vsync a {VSYNC_HZ:g} Hz no pasan "
                    "de ahi; `(vsync)` indica que el programa va sobrado y la cifra mide el monitor.", ""]
        out += ["", "### Evolucion", ""] + history_table(entries, history)
        changes = changes_table(entries)
        if changes:
            out += ["", "Casos cuyo CPI cambio un 1 % o mas respecto a la medida anterior:", ""] + changes
        out += [""]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", help="solo medidas con esta etiqueta")
    parser.add_argument("--history", type=int, default=5, help="medidas por prototipo en la evolucion")
    parser.add_argument("-o", "--output", type=Path, help="fichero de salida")
    parser.add_argument("--stdout", action="store_true", help="imprimir en vez de escribir fichero")
    args = parser.parse_args(argv)
    report = build_report(ROOT, args.label, args.history)
    if args.stdout:
        print(report)
        return 0
    output = args.output or ROOT / "reports" / "rendimiento" / f"{datetime.now():%Y%m%d-%H%M%S}-informe.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Informe escrito en {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
