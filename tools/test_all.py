#!/usr/bin/env python3
"""Ejecuta la suite de casos en TODOS los prototipos con placa y saca una matriz.

Para cada prototipo lanza `run_tests.py --backend <familia>-fpga -p N`, que sube
su bitstream y corre cada caso comparando con lo esperado, y junta el resultado
en una tabla: una fila por caso, una columna por prototipo, con PASS, FAIL o el
motivo del SKIP. Es el equivalente de conformidad de `bench-all` (que mide).

  test-all --family gpu --yes          las GPU: 12, 14, 22 y 29
  test-all --family cpu --yes          las CPU
  test-all -p 22 -p 29 --yes           solo esos
  test-all --list                      que prototipos probaria, sin tocar la placa

La matriz se escribe en `reports/pruebas/<fecha>-<familia>.md`. Un prototipo
cuyo bitstream no se puede cargar, o que no responde, queda marcado como
`ERROR` en toda su columna y no detiene a los demas. El codigo de salida es 0 solo
si no hay ningun FAIL ni ERROR: un SKIP por capacidades no es un fallo.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "x.tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from tools.bench_all import prototypes  # noqa: E402

RESULT = re.compile(r"^(PASS|FAIL) (\S+) \[[^\]]+\]")
SKIP = re.compile(r"^SKIP ([^\s:\[]+)(?: \[[^\]]+\])?:? ?(.*)$")
SUMMARY = re.compile(r"(\d+) caso\(s\), (\d+) fallo\(s\), (\d+) omitido")


def run_prototype(family: str, number: int, assume_yes: bool, extra: list[str]):
    """`(resultados, resumen, salida)`; `resultados[caso] = (estado, detalle)`."""
    command = [sys.executable, str(ROOT / "x.tests" / "run_tests.py"),
               "--backend", f"{family}-fpga", "-p", str(number)]
    if assume_yes:
        command.append("-y")
    command += extra
    print(f"$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    output = completed.stdout + completed.stderr
    results, summary = parse_output(output)
    return results, summary, output, completed.returncode


def parse_output(output: str):
    """`(resultados, resumen)` de la salida de `run_tests.py`."""
    results: dict[str, tuple[str, str]] = {}
    failing = None
    for line in output.splitlines():
        match = RESULT.match(line)
        if match:
            results[match.group(2)] = (match.group(1), "")
            failing = match.group(2) if match.group(1) == "FAIL" else None
            continue
        match = SKIP.match(line)
        if match:
            results[match.group(1)] = ("SKIP", match.group(2).strip())
            failing = None
            continue
        if failing and line.startswith("  "):
            state, detail = results[failing]
            results[failing] = (state, (detail + " " + line.strip()).strip())
    return results, SUMMARY.search(output)


def matrix(columns: list[tuple[str, dict, str | None]]) -> str:
    """Tabla en Markdown. `columns = [(titulo, resultados, error_de_arranque)]`."""
    names = sorted({name for _t, results, _e in columns for name in results})
    lines = ["| Caso | " + " | ".join(title for title, _r, _e in columns) + " |",
             "| --- | " + " | ".join("---" for _ in columns) + " |"]
    for name in names:
        cells = []
        for _title, results, error in columns:
            if name in results:
                cells.append(results[name][0])
            else:
                cells.append("ERROR" if error else "—")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(family: str, columns, totals) -> str:
    out = [f"# Pruebas en placa: {family.upper()}", "",
           f"Generado el {datetime.now():%Y-%m-%d %H:%M}.", "",
           "| Prototipo | Casos | PASS | FAIL | SKIP | Estado |", "| --- | ---: | ---: | ---: | ---: | --- |"]
    for (title, results, error), total in zip(columns, totals):
        counts = {k: sum(1 for s, _d in results.values() if s == k) for k in ("PASS", "FAIL", "SKIP")}
        out.append(f"| {title} | {len(results)} | {counts['PASS']} | {counts['FAIL']} | "
                   f"{counts['SKIP']} | {error or ('OK' if not counts['FAIL'] else 'FALLOS')} |")
    out += ["", "## Matriz", "", matrix(columns), ""]
    problems = [(t, n, d) for t, r, _e in columns for n, (s, d) in sorted(r.items()) if s == "FAIL"]
    if problems:
        out += ["## Fallos", ""]
        out += [f"- **{t}** `{n}`: {d or 'sin detalle'}" for t, n, d in problems]
        out.append("")
    skipped = {}
    for title, results, _e in columns:
        for name, (state, detail) in results.items():
            if state == "SKIP":
                skipped.setdefault(name, []).append((title, detail))
    if skipped:
        out += ["## Omitidos y por que", ""]
        for name in sorted(skipped):
            reasons = {d for _t, d in skipped[name]}
            where = ", ".join(t for t, _d in skipped[name])
            out.append(f"- `{name}` ({where}): " + "; ".join(sorted(r or 'sin motivo' for r in reasons)))
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--family", choices=("cpu", "gpu"), default="gpu")
    parser.add_argument("-p", "--prototype", action="append", type=int, metavar="N")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="aceptar la carga de bitstreams sin preguntar")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("cases", nargs="*", help="casos o directorios (por defecto, todos)")
    args = parser.parse_args(argv)

    chosen = [item for item in prototypes(args.family)
              if not args.prototype or item[1] in args.prototype]
    if args.list:
        for _family, _number, name in chosen:
            print(name)
        return 0
    if not chosen:
        parser.error("ningun prototipo con backend de placa coincide")

    columns, totals, failed = [], [], False
    begun = time.monotonic()
    # Secuencial a proposito: hay UNA placa, y cada prototipo le carga su bitstream.
    for family, number, name in chosen:
        started = time.monotonic()
        results, summary, output, code = run_prototype(family, number, args.yes, args.cases)
        error = None
        fails = sum(1 for s, _d in results.values() if s == "FAIL")
        if not results:
            error = "ERROR"
            tail = "\n".join(output.strip().splitlines()[-3:])
            print(f"!! {name}: sin resultados (codigo {code})\n{tail}", file=sys.stderr)
        elif code != 0 and not fails:
            # Salio mal sin ninguna linea FAIL: una excepcion del arnes a mitad
            # de la pasada. Lo parseado hasta entonces es verdad pero incompleto,
            # y dar «OK» a una placa con medio informe es peor que no darlo.
            error = f"INCOMPLETO (codigo {code})"
            tail = "\n".join(output.strip().splitlines()[-3:])
            print(f"!! {name}: la pasada termino con codigo {code} sin ningun "
                  f"FAIL; resultados parciales\n{tail}", file=sys.stderr)
        failed = failed or bool(error) or fails > 0
        print(f"--- {name}: " + (error or f"{len(results)} casos, {fails} fallos")
              + f" en {time.monotonic() - started:.0f} s", flush=True)
        columns.append((f"{number}", results, error))
        totals.append(summary.groups() if summary else None)

    report = build_report(args.family, columns, totals)
    output = args.output or ROOT / "reports" / "pruebas" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.family}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"\nMatriz escrita en {output} ({time.monotonic() - begun:.0f} s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
