#!/usr/bin/env python3
"""Resumen y archivo de una ejecucion de Diamond, con el esquema de `build_report.py`.

`summary.json` usa las mismas claves que el de nextpnr (`clocks` con `achieved` y
`constraint`, `utilization` con `used` y `available`) para que `build-list` y
`build-compare` puedan leer los dos. Se anaden las que nextpnr no tiene: hold,
holguras y la tabla de iteraciones de PAR.

El archivo va a `<proto>/reports/<fecha>-diamond/`, con `"tool": "diamond"` en
`metadata.json`: `build_report` y `build_runner` ignoran esas carpetas al decidir si el
bitstream de apio esta al dia.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

IMPL = "impl1"
PREFERENCE_RE = re.compile(r'^Preference:\s+FREQUENCY (?:NET|PORT) "([^"]+)"\s+([\d.]+)\s+MHz')
REPORT_RE = re.compile(r"^Report:\s+([\d.]+)\s*MHz is the maximum frequency")
EXCEEDS_RE = re.compile(r"^Error:\s+The following path exceeds requirements by ([\d.]+)\s*ns")
# "1 timing error detected" va en singular: con "errors" a secas, un unico error hacia
# desaparecer el reloj de la tabla (y salia PASS).
ITEMS_RE = re.compile(r"^\s*(\d+) items scored, (\d+) timing errors? detected")
SUMMARY_RE = re.compile(r"Timing errors:\s+(\d+) \(setup\), (\d+) \(hold\)")
USAGE_RE = re.compile(r"^\s*Number of ([^:]+?):\s+(\d+) out of (\d+)")
# El tiempo de cada iteracion sale en segundos ("30") y, desde el minuto, como
# "02:23" o "1:02:23": con solo \d+ la fila se descartaba y no quedaba iteracion guardada.
PAR_ROW_RE = re.compile(
    r"^(\d+_\d+)\s+(\*)?\s+(\d+)\s+(-?[\d.]+)\s+(\d+)\s+(-?[\d.]+)\s+(\d+)\s+(\d+(?::\d+)*)\s+(\S+)")


def _seconds(text: str) -> int:
    """'30' -> 30; '02:23' -> 143; '1:02:23' -> 3743."""
    total = 0
    for part in text.split(":"):
        total = total * 60 + int(part)
    return total


def parse_twr(path: Path) -> tuple[dict, dict]:
    """(clocks, errors) del TRACE final.

    TRACE imprime dos secciones, setup y luego hold, con las mismas `Preference:`.
    Los `Report: ... MHz` solo salen en la de setup, asi que al repetirse una
    preferencia se deja de leer. Las de 0 caminos puntuados (el puerto `clk_25mhz` o
    su red cuando solo alimenta al PLL) no cuentan: su "Report" no es de un reloj
    que limite nada. Un `FREQUENCY PORT` si cuenta si puntua caminos (la 3, sin PLL).
    """
    clocks: dict[str, dict] = {}
    errors = {"setup": None, "hold": None}
    seen: set[str] = set()
    current = None
    scored = 0
    in_setup = True
    # Una preferencia con errores no tiene linea "Report: ... MHz": TRACE lista los
    # caminos que fallan. Sin esto el reloj desaparecia y salia PASS con errores.
    # Se estima la Fmax desde el peor exceso: 1000 / (periodo exigido + exceso).
    #
    # Los errores "Minimum Pulse Width" (ancho minimo de pulso del reloj de un bloque de
    # E/S, p. ej. el SIOLOGIC del ODDRX1F a 370 MHz) NO son un camino: son un limite del
    # datasheet que nextpnr no comprueba y que ninguna colocacion arregla. Se cuentan
    # aparte, como aviso, y no entran en la Fmax estimada.
    # pending = [reloj, exigido, peor exceso de un camino, errores de ancho de pulso]
    pending: list | None = None
    block: list | None = None  # [exceso, es_ancho_de_pulso] del "Error:" que se esta leyendo
    pulse_total = 0

    def close_block() -> None:
        nonlocal block
        if block is not None and pending is not None:
            if block[1]:
                pending[3] += 1
            else:
                pending[2] = max(pending[2] or 0.0, block[0])
        block = None

    def flush() -> None:
        nonlocal pending, pulse_total
        close_block()
        if pending:
            name, constraint, worst, pulses = pending
            pulse_total += pulses
            if worst is not None:
                clocks[name] = {"achieved": 1000.0 / (1000.0 / constraint + worst),
                                "constraint": constraint, "estimated": True}
            elif pulses:
                # Todos los caminos cumplen y solo falla el ancho de pulso: no hay linea
                # "Report", asi que se da el reloj por cumplido (estimado).
                clocks[name] = {"achieved": constraint, "constraint": constraint,
                                "estimated": True}
        pending = None

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = SUMMARY_RE.search(line)
        if match:
            errors = {"setup": int(match.group(1)), "hold": int(match.group(2))}
        match = EXCEEDS_RE.match(line)
        if match:
            close_block()
            block = [float(match.group(1)), False]
        elif line.startswith("Passed:"):
            close_block()  # un ancho de pulso aprobado no es del "Error:" anterior
        elif block is not None and "based on Minimum Pulse Width" in line:
            block[1] = True
        if line.startswith("Preference:"):
            flush()
            match = PREFERENCE_RE.match(line)
            current = None
            scored = 0
            if match:
                name = match.group(1)
                if name in seen:
                    in_setup = False
                seen.add(name)
                if in_setup:
                    current = (name, float(match.group(2)))
            elif line.split('"')[1:2] and line.split('"')[1] not in seen:
                seen.add(line.split('"')[1])
            continue
        match = ITEMS_RE.match(line)
        if match and current:
            scored = int(match.group(1))
            if int(match.group(2)) > 0:
                pending = [current[0], current[1], None, 0]
            continue
        match = REPORT_RE.match(line)
        if match and current and in_setup and scored:
            clocks[current[0]] = {"achieved": float(match.group(1)), "constraint": current[1]}
            current = None
    flush()
    errors["pulse_width"] = pulse_total
    return clocks, errors


def parse_par(path: Path) -> list[dict]:
    """Filas de la tabla de iteraciones de PAR (`5_3`: nivel de colocacion _ cost table)."""
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = PAR_ROW_RE.match(line)
        if match:
            rows.append({
                "iteration": match.group(1), "saved": bool(match.group(2)),
                "unrouted": int(match.group(3)),
                "setup_slack": float(match.group(4)), "setup_score": int(match.group(5)),
                "hold_slack": float(match.group(6)), "hold_score": int(match.group(7)),
                "run_time_s": _seconds(match.group(8)), "status": match.group(9),
            })
    return rows


def parse_mrp(path: Path) -> dict:
    usage = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = USAGE_RE.match(line)
        if match and match.group(1) not in usage:
            usage[match.group(1)] = {"used": int(match.group(2)),
                                     "available": int(match.group(3))}
    return usage


def summarize(impl: Path) -> dict:
    twr = next(impl.glob("*.twr"), None)
    par = next(impl.glob("*.par"), None)
    mrp = next(impl.glob("*.mrp"), None)
    clocks, errors = parse_twr(twr) if twr else ({}, {"setup": None, "hold": None})
    iterations = parse_par(par) if par else []
    saved = next((row for row in iterations if row["saved"]), None)
    return {
        "tool": "diamond",
        "clocks": clocks,
        "utilization": parse_mrp(mrp) if mrp else {},
        "setup_errors": errors["setup"], "hold_errors": errors["hold"],
        "pulse_width_errors": errors.get("pulse_width", 0),
        "worst_setup_slack": saved["setup_slack"] if saved else None,
        "worst_hold_slack": saved["hold_slack"] if saved else None,
        "saved_iteration": saved["iteration"] if saved else None,
        "par_iterations": iterations,
    }


def summary_text(summary: dict, label: str, elapsed: float, strategy: list[str]) -> str:
    lines = [f"Label: {label}", f"Elapsed: {elapsed:.1f} s", "Tool: diamond (Synplify + MAP/PAR/TRACE)"]
    if strategy:
        lines.append("Strategy: " + " ".join(strategy))
    for name, values in summary["clocks"].items():
        verdict = "PASS" if values["achieved"] >= values["constraint"] else "FAIL"
        lines.append(f"{name}: {values['achieved']:.2f} MHz; required {values['constraint']:.2f} MHz; {verdict}")
    lines.append(f"TRACE errors: {summary['setup_errors']} setup, {summary['hold_errors']} hold")
    if summary.get("pulse_width_errors"):
        lines.append(f"WARNING: {summary['pulse_width_errors']} minimum-pulse-width error(s) counted in "
                     "the setup errors above: datasheet limit of an I/O block clock (e.g. ODDRX1F "
                     "above ~250 MHz). nextpnr does not check it; no placement fixes it.")
    lines.append(f"Saved PAR iteration {summary['saved_iteration']}: worst setup slack "
                 f"{summary['worst_setup_slack']} ns, worst hold slack {summary['worst_hold_slack']} ns")
    lines.append("PAR iterations (iteration, setup slack, hold slack, saved):")
    for row in summary["par_iterations"]:
        lines.append(f"  {row['iteration']:<6} {row['setup_slack']:>8} {row['hold_slack']:>8}"
                     f"{'  *' if row['saved'] else ''}")
    for name, values in summary["utilization"].items():
        lines.append(f"{name}: {values['used']} / {values['available']}")
    return "\n".join(lines) + "\n"


def archive(proto: Path, out: Path, started: datetime, elapsed: float, exit_code: int,
            command: list[str], strategy: list[str], label: str = "diamond",
            phases: dict | None = None) -> Path:
    """Copia lo relevante de `.diamond/` a `reports/<fecha>-<label>/` y escribe los resumenes."""
    from tools.build_report import synthesizable_source_hashes

    impl = out / IMPL
    summary = summarize(impl)
    summary.update(label=label, archive_only=False, elapsed_seconds=elapsed)
    if phases:
        summary["phases"] = phases
    folder = proto / "reports" / f"{started:%Y%m%d-%H%M%S-%f}-{label}"
    folder.mkdir(parents=True)
    metadata = {
        "label": label, "tool": "diamond", "archive_only": False, "incremental": False,
        "command": command, "strategy": strategy,
        "source_sha256": synthesizable_source_hashes(proto),
        "started": started.isoformat(), "exit_code": exit_code, "elapsed_seconds": elapsed,
    }
    if phases:
        metadata["phases"] = phases
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (folder / "summary.txt").write_text(summary_text(summary, label, elapsed, strategy),
                                        encoding="utf-8")
    sources = {out / "diamond.log": "build.log", out / "build.tcl": "build.tcl",
               out / "hardware.bit": "hardware.bit"}
    for pattern in ("*.twr", "*.par", "*.mrp"):
        for path in impl.glob(pattern):
            sources[path] = f"hardware{path.suffix}"
    for path, name in sources.items():
        if path.is_file():
            shutil.copyfile(path, folder / name)
    return folder


if __name__ == "__main__":  # resumen suelto de un .diamond ya generado
    from tools.prototype import find_repo_root, resolve_prototype

    target = resolve_prototype(sys.argv[1], find_repo_root())
    print(summary_text(summarize(target / ".diamond" / IMPL), "diamond", 0.0, []))
