#!/usr/bin/env python3
"""Mide todos los prototipos con placa (CPU y GPU) y genera el informe.

Para cada prototipo ejecuta la suite de casos con `run_tests.py --measure`, que
sube su bitstream a la placa, corre cada caso leyendo los contadores de ciclos,
e instrucciones y archiva el resultado en `<prototipo>/reports/`. Al final,
`perf_report` junta lo archivado en un informe con una tabla por magnitud.

  bench-all --yes                   todos los prototipos, CPU y GPU
  bench-all --family gpu --yes      solo las GPU
  bench-all -p 21 -p 22 --yes       solo esos
  bench-all --list                  que prototipos mediria, sin tocar la placa
  bench-all --report-only           solo regenera el informe

Cambiar de prototipo recarga el bitstream, que puede incluir sintetizar si sus
fuentes cambiaron desde el ultimo build: la primera pasada tarda. `--yes` acepta
esas cargas; sin el, el runner pregunta antes de cada una.

Un prototipo que falla no detiene a los demas: se anota y el resumen final dice
cuales. Las medidas llevan la etiqueta `--label` (por defecto `bench`), y el
informe puede filtrar por ella para comparar solo medidas hechas igual.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "x.tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from backends import fpga_cpu  # noqa: E402
from backends import fpga_sys  # noqa: E402
from backends import fpga_gpu  # noqa: E402


def _number(directory: Path) -> int:
    match = re.match(r"(\d+)", directory.name)
    return int(match.group(1)) if match else 0


def prototypes(family: str, core: bool = False):
    """`[(familia, numero, carpeta)]` de los prototipos con backend de placa.

    Con `core=True` la 36 y la 37 salen ADEMÁS como GPU (backend `fpga-sys`): son
    CPU y GPU a la vez, y salen siempre como CPU. Por defecto no, porque `bench`
    mide y `fpga-sys` todavía no admite `--measure`.
    """
    found = []
    for name, versions in (("cpu", fpga_cpu.VERSIONS), ("gpu", fpga_gpu.VERSIONS)):
        if family not in ("all", name):
            continue
        for version in versions.values():
            directory = version["monitor_path"].parent
            found.append((name, _number(directory), directory.name))
    if core and family in ("all", "gpu"):
        for version in fpga_sys.VERSIONS.values():
            directory = version["monitor_path"].parent
            found.append(("gpu", _number(directory), directory.name))
    return sorted(found, key=lambda item: (item[0], item[1]))


def board_backend(family: str, number: int) -> str:
    """El `--backend` de `run_tests.py` para este prototipo y esta familia.

    Casi siempre `fpga-<familia>`. Una GPU que cuelga de una CPU (36 y 37) se
    prueba con `fpga-sys`, porque `fpga-gpu` solo conoce las carpetas sin `cpu.v`.
    """
    if family == "gpu" and any(
            _number(v["monitor_path"].parent) == number
            for v in fpga_sys.VERSIONS.values()):
        return "fpga-sys"
    return f"fpga-{family}"


def measure(family: str, number: int, label: str, assume_yes: bool, extra: list[str]) -> int:
    command = [sys.executable, str(ROOT / "x.tests" / "run_tests.py"), "--measure",
               "--backend", f"fpga-{family}", "-p", str(number), "--measure-label", label]
    if assume_yes:
        command.append("-y")
    command += extra
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--family", choices=("all", "cpu", "gpu"), default="all")
    parser.add_argument("-p", "--prototype", action="append", type=int, metavar="N",
                        help="solo este prototipo (se puede repetir)")
    parser.add_argument("--label", default="bench")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="aceptar la carga de bitstreams sin preguntar")
    parser.add_argument("--list", action="store_true", help="solo listar, sin tocar la placa")
    parser.add_argument("--report-only", action="store_true", help="solo regenerar el informe")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--history", type=int, default=5)
    parser.add_argument("measure_args", nargs="*",
                        help="casos o directorios a medir (por defecto, todos)")
    args = parser.parse_args(argv)

    chosen = [item for item in prototypes(args.family)
              if not args.prototype or item[1] in args.prototype]
    if args.prototype:
        missing = sorted(set(args.prototype) - {item[1] for item in chosen})
        if missing:
            parser.error(f"sin backend de placa: {', '.join(map(str, missing))}")

    if args.list:
        for family, number, name in chosen:
            print(f"{family}  {name}")
        return 0

    failures = []
    if not args.report_only:
        begun = time.monotonic()
        for family, number, name in chosen:
            print(f"\n=== {name} ({family.upper()}) ===", flush=True)
            started = time.monotonic()
            code = measure(family, number, args.label, args.yes, args.measure_args)
            print(f"--- {name}: {'OK' if code == 0 else f'FALLO (codigo {code})'} "
                  f"en {time.monotonic() - started:.0f} s", flush=True)
            if code != 0:
                failures.append(name)
        print(f"\nMedido en {time.monotonic() - begun:.0f} s")

    if not args.no_report:
        from tools.perf_report import main as report_main
        report_main(["--history", str(args.history)])
    if failures:
        print(f"\nFallaron: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
