#!/usr/bin/env python3
"""Ejecuta la suite de un prototipo: fixtures (si las tiene) + tests Python
(si los tiene) + regresión RTL de apio (si tiene apio.ini) + lint opcional.

Genérico: no depende de qué prototipo es. Cada paso se salta con claridad si
no aplica a ese prototipo en concreto, en vez de fingir que existe."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prototype import PrototypeResolutionError, find_apio_binary, find_repo_root, resolve_prototype


def run_step(name: str, command: list[str], cwd: Path) -> int:
    print(f"== {name}", flush=True)
    print(f"$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=str(cwd))
    if completed.returncode != 0:
        print(f"!! {name} falló (exit {completed.returncode})", file=sys.stderr)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--prototype", required=True)
    parser.add_argument("--quick", action="store_true", help="solo fixtures + tests Python, sin apio test")
    parser.add_argument("--lint", action="store_true", help="añade apio lint")
    parser.add_argument("--lint-only", action="store_true",
                        help="solo apio lint: sin fixtures, tests Python ni regresión RTL")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.lint_only:
        args.lint = True

    root = find_repo_root(Path.cwd())
    try:
        prototype_dir = resolve_prototype(args.prototype, root=root)
    except PrototypeResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Using prototype: {prototype_dir.name}")

    ran_something = False
    failures: list[str] = []

    fixtures_script = prototype_dir / "make_fixtures.py"
    if fixtures_script.exists() and not args.lint_only:
        ran_something = True
        if run_step("fixtures", [sys.executable, str(fixtures_script)], prototype_dir) != 0:
            failures.append("fixtures")
            return _summarize(failures)

    if any(prototype_dir.glob("test_*.py")) and not args.lint_only:
        ran_something = True
        command = [sys.executable, "-m", "unittest", "discover", "-s", str(prototype_dir), "-p", "test_*.py"]
        if args.verbose:
            command.append("-v")
        if run_step("tests Python", command, prototype_dir) != 0:
            failures.append("tests Python")

    apio_ini = prototype_dir / "apio.ini"
    skipped_rtl_test = False
    if apio_ini.exists():
        apio = find_apio_binary(root)
        if args.quick or args.lint_only:
            skipped_rtl_test = True
        else:
            ran_something = True
            if run_step("regresión RTL (apio test)", [apio, "test", "-p", str(prototype_dir)], prototype_dir) != 0:
                failures.append("apio test")
        if args.lint:
            ran_something = True
            if run_step("lint (apio lint)", [apio, "lint", "-p", str(prototype_dir)], prototype_dir) != 0:
                failures.append("apio lint")
    elif args.lint:
        print(f"aviso: {prototype_dir.name} no tiene apio.ini; --lint no aplica.", file=sys.stderr)

    if not ran_something:
        if skipped_rtl_test:
            print(f"aviso: {prototype_dir.name} no tiene test_*.py; la regresión RTL se omitió por --quick.", file=sys.stderr)
        else:
            print(f"aviso: {prototype_dir.name} no tiene nada que probar (ni test_*.py, ni apio.ini).", file=sys.stderr)

    return _summarize(failures)


def _summarize(failures: list[str]) -> int:
    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
