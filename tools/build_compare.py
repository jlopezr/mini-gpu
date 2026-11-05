#!/usr/bin/env python3
"""Compara el ultimo build de apio (yosys + nextpnr) y el de Diamond de cada prototipo.

Lee `reports/*/summary.json` de los dos flujos (esquema comun, ver diamond_report.py).
Una fila por prototipo y herramienta, para ver juntas las dos cifras de cada reloj.

Que no es comparable:
  * nextpnr no analiza hold: "hold" solo existe para Diamond.
  * Los recursos tienen otro nombre y otro recuento: TRELLIS_COMB de nextpnr incluye
    acarreos y mux que Diamond cuenta aparte en sus LUT4s. Sirven para comparar
    magnitud, no a la unidad.
  * El Fmax de nextpnr es el del reloj tras enrutar; el de Diamond, el `Report: ... MHz`
    de TRACE para esa preferencia.
`*` en REPORT indica que ese informe se hizo con fuentes distintas de las actuales.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_report import (
    _metadata_source_hashes, apio_report_metadata, is_diamond_report,
    synthesizable_source_hashes,
)
from tools.prototype import find_repo_root, list_prototypes, resolve_prototype

# (apio, diamond): nombre del recurso en cada summary.json
RESOURCES = {"LUT": ("TRELLIS_COMB", "LUT4s"), "FF": ("TRELLIS_FF", "registers"),
             "EBR": ("DP16KD", "block RAMs")}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def latest_reports(proto: Path) -> dict[str, Path | None]:
    """Carpeta del ultimo informe con summary.json de cada herramienta."""
    found: dict[str, Path | None] = {"apio": None, "diamond": None}
    for metadata in apio_report_metadata(proto):
        if (metadata.parent / "summary.json").is_file():
            found["apio"] = metadata.parent
            break
    history = proto / "reports"
    diamond = sorted((d for d in history.glob("*")
                      if (d / "summary.json").is_file() and is_diamond_report(d)),
                     key=lambda d: d.name, reverse=True) if history.is_dir() else []
    found["diamond"] = diamond[0] if diamond else None
    return found


def _limiting(clocks: dict) -> tuple[str, float, float] | None:
    rows = [(name.removeprefix("$glbnet$").split("$")[0], float(v.get("achieved", 0)),
             float(v.get("constraint", 0))) for name, v in clocks.items()]
    return min(rows, key=lambda r: r[1] / max(r[2], 0.001)) if rows else None


def _resource(summary: dict, tool: str, key: str) -> str:
    name = RESOURCES[key][0 if tool == "apio" else 1]
    value = summary.get("utilization", {}).get(name)
    return str(value["used"]) if value else "-"


def _seconds(value) -> str:
    return "-" if value is None else f"{float(value):.0f}"


def _times(summary: dict, metadata: dict) -> list[str]:
    """[TOTAL, SYNTH, PNR] en segundos; los informes antiguos no separan fases."""
    total = summary.get("elapsed_seconds", metadata.get("elapsed_seconds"))
    phases = summary.get("phases") or metadata.get("phases") or {}
    return [_seconds(total), _seconds(phases.get("synthesis")), _seconds(phases.get("pnr"))]


def row(proto: Path, tool: str, folder: Path | None, current: dict) -> list[str]:
    if folder is None:
        return [proto.name, tool] + ["-"] * 13
    summary = _load(folder / "summary.json")
    metadata = _load(folder / "metadata.json")
    stale = "" if _metadata_source_hashes(metadata) == current else "*"
    limiting = _limiting(summary.get("clocks", {}))
    if limiting:
        clock, achieved, required = limiting
        verdict = "PASS" if achieved >= required else "FAIL"
        if verdict == "PASS" and summary.get("pulse_width_errors"):
            verdict = "WARN"  # solo falla el ancho minimo de pulso de un bloque de E/S (datasheet)
        fmax = f"{achieved:.1f}/{required:.1f}"
    else:
        clock, verdict, fmax = "-", "-", "-"
    hold = summary.get("hold_errors")
    slack = summary.get("worst_setup_slack")
    from tools.build_report import configured_seed
    from tools.build_runner import diamond_effort
    seed = str(configured_seed(proto) or "-") if tool == "apio" else diamond_effort(folder)
    return [proto.name, tool, clock, fmax, verdict,
            "n/a" if tool == "apio" else ("-" if hold is None else str(hold)),
            "-" if slack is None else f"{slack:+.3f}", seed,
            *_times(summary, metadata),
            _resource(summary, tool, "LUT"), _resource(summary, tool, "FF"),
            _resource(summary, tool, "EBR"), folder.name[:15] + stale]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prototype", "-p", action="append", default=[],
                        help="numero, nombre o ruta (repetible); por defecto, todos con informes")
    args = parser.parse_args()

    root = find_repo_root()
    protos = ([resolve_prototype(p, root) for p in args.prototype] if args.prototype
              else [p for p in list_prototypes(root) if (p / "reports").is_dir()])
    header = ["PROTOTYPE", "TOOL", "CLOCK", "FMAX/REQ", "TIMING", "HOLD", "SLACK(ns)", "SEED",
              "TOTAL(s)", "SYNTH(s)", "PNR(s)", "LUT", "FF", "EBR", "REPORT"]
    rows = []
    for proto in protos:
        reports = latest_reports(proto)
        if not any(reports.values()):
            continue
        current = synthesizable_source_hashes(proto)
        for tool in ("apio", "diamond"):
            rows.append(row(proto, tool, reports[tool], current))
    if not rows:
        print("No hay informes que comparar.")
        return 1
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    # Mismos colores de TOOL que `build-list --prototypes`; sin terminal o con NO_COLOR, sin ANSI.
    use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    tool_colors = {"apio": "34", "diamond": "35"}
    timing_colors = {"PASS": "32", "WARN": "33", "FAIL": "31"}  # los de build-list
    last = None
    for r in rows:
        if last is not None and r[0] != last:
            print()
        last = r[0]
        cells = [c.ljust(w) for c, w in zip(r, widths)]
        if use_color and r[1] in tool_colors:
            cells[1] = f"\033[{tool_colors[r[1]]}m{cells[1]}\033[0m"
        if use_color and r[4] in timing_colors:
            cells[4] = f"\033[{timing_colors[r[4]]}m{cells[4]}\033[0m"
        print("  ".join(cells))
    print("\nHOLD n/a: nextpnr no analiza hold. SLACK es la holgura de setup de la iteracion "
          "guardada por PAR (solo Diamond).\nSYNTH es yosys / Synplify; PNR es todo lo que sigue "
          "(nextpnr + ecppack / Translate..Bitgen). Los informes anteriores a esta medida solo "
          "tienen TOTAL.\n* en REPORT: informe con fuentes distintas de las actuales.\n"
          "SEED: apio, la semilla fijada en apio.ini; Diamond, la cost table de la iteracion de PAR "
          "guardada ('-' si valio el primer intento: no hizo falta buscar).\n"
          "WARN: los caminos cumplen y solo falla el ancho minimo de pulso de un bloque de E/S "
          "(limite del datasheet que nextpnr no comprueba); FMAX es entonces el exigido, no medido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
