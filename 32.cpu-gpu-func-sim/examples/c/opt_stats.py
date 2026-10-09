#!/usr/bin/env python3
"""Cuanto aportan los pases de mini-opt: instrucciones por pase y ejecutadas con y sin ellos.

    python examples/c/opt_stats.py [--out tabla.md]

Compila los ejemplos dos veces, con los pases que ya habia (`intrinsics,kernels,ssy`: lo
imprescindible para que corra) y con los de ahora (`DEFAULT_PASSES`), y compara en el simulador
las instrucciones que se ejecutan (compare.py y compare_race.py) frente al ensamblador. Antes
de eso, por cada .c, lo que cada pase anade o quita al texto (`mini-opt --stats`).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import build as c_build  # noqa: E402
import compare  # noqa: E402
import compare_race  # noqa: E402

BEFORE = "intrinsics,kernels,ssy"
SOURCES = ["dma/gpu_kernels.c", "race/rotate.c", "race/life.c", "race/blur.c", "race/cube.c", "simt/diverge.c"]


def static_stats(source: Path) -> str:
    plain = c_build.BUILD / f"{source.stem}.stats.s"
    c_build.BUILD.mkdir(exist_ok=True)
    c_build.run(c_build.TOOLS / "mini-lcc", source, "--no-crt", "-I", c_build.SYSTEM, "-o", plain)
    done = subprocess.run([sys.executable, str(c_build.TOOLS / "mini-opt"), str(plain), "-o", os.devnull,
                           "--stats"], capture_output=True, text=True)
    return done.stderr.rstrip()


def run_with(passes: str | None):
    if passes is None:
        os.environ.pop("MINI_OPT_PASSES", None)
    else:
        os.environ["MINI_OPT_PASSES"] = passes
    return compare.compare(), {name: compare_race.compare(name) for name in compare_race.WORKLOADS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="guarda la tabla en markdown")
    args = parser.parse_args()
    out: list[str] = ["## Texto: lo que añade (+) o quita (-) cada pase\n"]
    for name in SOURCES:
        out += [f"`{name}`", "```text", static_stats(HERE / name), "```", ""]
    before_sys, before_race = run_with(BEFORE)
    after_sys, after_race = run_with(None)
    out.append("## Instrucciones ejecutadas (simulador), C frente a ensamblador\n")
    out += ["| Carga | Ensamblador | C antes | C ahora | antes / ens. | ahora / ens. | mejora |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for (w, a, c0, _, _), (_, _, c1, _, _) in zip(before_sys, after_sys):
        out.append(f"| {w.name} | {a:,} | {c0:,} | {c1:,} | {c0 / a:.2f} | {c1 / a:.2f} | {c0 / c1:.2f}x |")
    for workload in compare_race.WORKLOADS:
        for (name, unit, a, c0, _), (_, _, _, c1, _) in zip(before_race[workload], after_race[workload]):
            out.append(f"| {workload}, {name} ({unit.split()[-1]}) | {a:,} | {c0:,} | {c1:,} | {c0 / a:.2f} | "
                       f"{c1 / a:.2f} | {c0 / c1:.2f}x |")
    text = "\n".join(out)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
