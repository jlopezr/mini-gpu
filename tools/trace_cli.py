#!/usr/bin/env python3
"""Interfaz de línea de comandos de la trazabilidad documental."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.prototype import find_repo_root
from tools.traceability import ModelBuilder, Resolver


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="trace", description="Comprueba la trazabilidad Markdown.")
    commands = result.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="resuelve enlaces, documentos y secciones")
    check.add_argument("paths", nargs="*", type=Path, help="ficheros o directorios (por defecto, todo el repo)")
    check.add_argument("--root", type=Path, help="raíz del repositorio")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = args.root.resolve() if args.root else find_repo_root(Path.cwd())
        model = ModelBuilder().build(root, args.paths or None)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    diagnostics = Resolver().resolve(model)
    for diagnostic in diagnostics:
        print(diagnostic.format(root))
    if diagnostics:
        print(f"FAIL: {len(diagnostics)} problema(s), {len(model.observations)} observaciones")
        return 1
    print(f"OK: {len(model.identities)} identidades, {len(model.observations)} observaciones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
