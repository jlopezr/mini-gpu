"""Filtro entre el `.s` del compilador y `mini-asm`: aplica pases a un `.s`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import OptError, Unit, parse_unit, render_unit
from .passes import ssy
from .registry import DEFAULT_PASSES, PASSES


def count_instructions(unit: Unit) -> int:
    return sum(1 for line in unit.lines() if line.kind == "instr")


def optimize(source: str, passes: list[str] | None = None, path: str = "<entrada>",
             stats: dict | None = None) -> str:
    """Aplica los pases (por defecto `DEFAULT_PASSES`) a un `.s` y devuelve el nuevo."""
    passes = DEFAULT_PASSES if passes is None else passes
    stats = stats if stats is not None else {}
    unit = parse_unit(source, path)
    for name in passes:
        if name not in PASSES:
            raise OptError(f"pase desconocido '{name}' (--list-passes)")
        before = count_instructions(unit)
        PASSES[name][0](unit, stats)
        stats[f"{name}.instrs"] = count_instructions(unit) - before
    return render_unit(unit)


def print_stats(stats: dict, passes: list[str] | None) -> None:
    """Una linea por pase: instrucciones estaticas que anade (+) o quita (-) y sus contadores."""
    names = DEFAULT_PASSES if passes is None else passes
    total = 0
    for name in names:
        delta = stats.get(f"{name}.instrs", 0)
        total += delta
        extra = ", ".join(f"{k.split('.', 1)[1] if '.' in k else k}={v}" for k, v in stats.items()
                          if (k == name or k.startswith(name + ".")) and k != f"{name}.instrs")
        print(f"  {name:11s} {delta:+5d} instrucciones  {extra}", file=sys.stderr)
    print(f"  {'total':11s} {total:+5d} instrucciones (estaticas)", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Filtro entre el `.s` del compilador y `mini-asm`: aplica pases a un `.s`.")
    parser.add_argument("input", nargs="?", type=Path, help=".s de entrada")
    parser.add_argument("-o", "--output", type=Path, help="`.s` de salida (por defecto stdout)")
    parser.add_argument("--passes", help="pases separados por coma, en orden "
                        f"(por defecto {','.join(DEFAULT_PASSES)}; vacio = ninguno)")
    parser.add_argument("--ssy-all", action="store_true",
                        help="pase ssy: tratar todo salto condicional como divergente")
    parser.add_argument("--stats", action="store_true", help="resumen de lo que hizo cada pase")
    parser.add_argument("--list-passes", action="store_true")
    args = parser.parse_args(argv)
    if args.list_passes:
        for name, (_, doc) in PASSES.items():
            print(f"{name:12s} {doc}")
        return 0
    if args.input is None:
        parser.error("hace falta un .s de entrada")
    passes = None if args.passes is None else [p for p in args.passes.split(",") if p]
    ssy.SSY_ALL = args.ssy_all
    stats: dict = {}
    try:
        text = optimize(args.input.read_text(encoding="utf-8"), passes, str(args.input), stats)
    except OptError as error:
        print(f"mini-opt: {error}", file=sys.stderr)
        return 1
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.stats:
        print_stats(stats, passes)
    return 0
