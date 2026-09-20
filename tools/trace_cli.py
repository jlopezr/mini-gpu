#!/usr/bin/env python3
"""Interfaz de línea de comandos de la trazabilidad documental."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.prototype import find_repo_root
from tools.traceability import ImpactAnalyzer, ModelBuilder, Resolver


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="trace", description="Comprueba y explora la trazabilidad del proyecto.")
    commands = result.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="valida el Project Model y sus relaciones")
    check.add_argument("paths", nargs="*", type=Path, help="ficheros o directorios (por defecto, todo el repo)")
    check.add_argument("--root", type=Path, help="raíz del repositorio")
    check.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")
    show = commands.add_parser("show", help="explica una identidad y sus relaciones")
    show.add_argument("identity", help="identidad semántica, por ejemplo REQ-001")
    show.add_argument("--root", type=Path, help="raíz del repositorio")
    show.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")
    impact = commands.add_parser("impact", help="explica qué identidades quedan afectadas")
    impact.add_argument("target", help="identidad o ruta de un recurso, incluso borrado")
    impact.add_argument("--depth", type=int, help="profundidad máxima del recorrido")
    impact.add_argument("--json", action="store_true", help="emite una respuesta JSON")
    impact.add_argument("--root", type=Path, help="raíz del repositorio")
    impact.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = args.root.resolve() if args.root else find_repo_root(Path.cwd())
        paths = args.paths or None if args.command == "check" else None
        model = ModelBuilder(use_cache=not args.no_cache).build(root, paths)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    resolver = Resolver()
    if args.command == "show":
        return show_identity(root, model, resolver, args.identity)
    if args.command == "impact":
        return show_impact(root, model, args.target, args.depth, args.json)

    diagnostics = resolver.resolve(model)
    for diagnostic in diagnostics:
        print(diagnostic.format(root))
    if diagnostics:
        print(f"FAIL: {len(diagnostics)} problema(s), {len(model.observations)} observaciones")
        return 1
    print(f"OK: {len(model.identities)} identidades, {len(model.observations)} observaciones "
          f"(cache: {model.cache_hits} reutilizados, {model.cache_misses} leídos)")
    return 0


def show_impact(root: Path, model, requested: str, depth: int | None, as_json: bool) -> int:
    try:
        result = ImpactAnalyzer().analyze(model, requested, depth)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if result.resolution.diagnostics:
        for diagnostic in result.resolution.diagnostics:
            print(diagnostic.format(root), file=sys.stderr)
        print("error: no se puede calcular impacto sobre un grafo inválido", file=sys.stderr)
        return 1
    if as_json:
        payload = {
            "target": requested,
            "deletedResource": result.deleted_resource,
            "seeds": [_identity_json(item, root) for item in result.seeds],
            "impacted": [{
                **_identity_json(item.identity, root),
                "depth": item.depth,
                "path": [{
                    "from": hop.origin, "to": hop.destination,
                    "relation": hop.relation, "direction": hop.direction,
                } for hop in item.path],
            } for item in result.impacted],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    suffix = " (recurso borrado; datos de caché)" if result.deleted_resource else ""
    print(f"Impacto de {requested}{suffix}")
    print("Origen: " + ", ".join(item.key for item in result.seeds))
    if not result.impacted:
        print("sin identidades afectadas")
        return 0
    for heading, items in (
        ("Directamente afectados", [item for item in result.impacted if item.depth == 1]),
        ("Transitivamente afectados", [item for item in result.impacted if item.depth > 1]),
    ):
        if not items:
            continue
        print(f"{heading}:")
        for item in items:
            print(f"  {item.identity.key} [{item.identity.element_type}] depth={item.depth}")
            print(f"    {_format_route(item.path)}")
    return 0


def _identity_json(identity, root: Path) -> dict:
    return {
        "id": identity.key,
        "elementType": identity.element_type,
        "location": identity.location.display(root),
    }


def _format_route(path) -> str:
    parts = [path[0].origin]
    for hop in path:
        if hop.direction == "outgoing":
            parts.append(f"--{hop.relation}--> {hop.destination}")
        else:
            parts.append(f"<--{hop.relation}-- {hop.destination}")
    return " ".join(parts)


def show_identity(root: Path, model, resolver: Resolver, requested: str) -> int:
    matches = [item for item in model.identities if item.key == requested]
    if not matches:
        print(f"error: no existe la identidad '{requested}'", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"error: la identidad '{requested}' está duplicada", file=sys.stderr)
        for item in matches:
            print(f"  {item.location.display(root)}", file=sys.stderr)
        return 1

    identity = matches[0]
    analysis = resolver.analyze(model)
    description = identity.artifact_type if identity.element_type == "artifact" else identity.element_type
    print(f"{identity.key} [{description}]")
    print(f"declarada en {identity.location.display(root)}")
    if identity.parent_facet:
        print(f"parent-facet: {identity.parent_facet}")
    connected = [
        relation for relation in analysis.relations
        if relation.source == identity or relation.target == identity
    ]
    if not connected:
        print("sin relaciones")
        return 0
    for relation in connected:
        if relation.source == identity:
            print(f"  {relation.kind} -> {relation.target.key} "
                  f"({relation.target.location.display(root)})")
        else:
            print(f"  <- {relation.kind} {relation.source.key} "
                  f"({relation.source.location.display(root)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
