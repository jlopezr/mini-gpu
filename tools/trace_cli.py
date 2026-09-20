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
    show = commands.add_parser("show", help="explica una identidad y sus relaciones")
    show.add_argument("identity", help="identidad semántica, por ejemplo REQ-001")
    show.add_argument("--root", type=Path, help="raíz del repositorio")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = args.root.resolve() if args.root else find_repo_root(Path.cwd())
        paths = args.paths or None if args.command == "check" else None
        model = ModelBuilder().build(root, paths)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    resolver = Resolver()
    if args.command == "show":
        return show_identity(root, model, resolver, args.identity)

    diagnostics = resolver.resolve(model)
    for diagnostic in diagnostics:
        print(diagnostic.format(root))
    if diagnostics:
        print(f"FAIL: {len(diagnostics)} problema(s), {len(model.observations)} observaciones")
        return 1
    print(f"OK: {len(model.identities)} identidades, {len(model.observations)} observaciones")
    return 0


def show_identity(root: Path, model, resolver: Resolver, requested: str) -> int:
    semantic_id = requested.upper()
    matches = [item for item in model.identities if item.semantic_id == semantic_id]
    if not matches:
        print(f"error: no existe la identidad '{requested}'", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"error: la identidad '{semantic_id}' está duplicada", file=sys.stderr)
        for item in matches:
            print(f"  {item.location.display(root)}", file=sys.stderr)
        return 1

    identity = matches[0]
    analysis = resolver.analyze(model)
    print(f"{identity.semantic_id} [{identity.kind}]")
    print(f"declarada en {identity.location.display(root)}")
    connected = [
        relation for relation in analysis.relations
        if relation.source == identity or relation.target == identity
    ]
    if not connected:
        print("sin relaciones")
        return 0
    for relation in connected:
        if relation.source == identity:
            print(f"  {relation.kind} -> {relation.target.semantic_id} "
                  f"({relation.target.location.display(root)})")
        else:
            print(f"  <- {relation.kind} {relation.source.semantic_id} "
                  f"({relation.source.location.display(root)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
