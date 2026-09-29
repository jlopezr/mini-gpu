#!/usr/bin/env python3
"""Interfaz de línea de comandos de la trazabilidad documental."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.prototype import find_repo_root
from tools.traceability import CORE_QUERIES, CORE_RULES, Graph, ImpactAnalyzer, ModelBuilder
from tools.traceability.coverage import file_coverage, repeated, unique_untraced
from tools.traceability.dedupe import apply_plan, build_plan


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="trace", description="Comprueba y explora la trazabilidad del proyecto.")
    commands = result.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="valida el Project Model y sus relaciones")
    check.add_argument("paths", nargs="*", type=Path, help="ficheros o directorios (por defecto, todo el repo)")
    check.add_argument("--root", type=Path, help="raíz del repositorio")
    check.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")
    show = commands.add_parser("show", help="explica una identidad y sus relaciones")
    show.add_argument("identity", help="identidad semántica, por ejemplo REQ-001")
    show.add_argument("--format", choices=("text", "json"), default="text")
    show.add_argument("--root", type=Path, help="raíz del repositorio")
    show.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")
    impact = commands.add_parser("impact", help="explica qué identidades quedan afectadas")
    impact.add_argument("target", help="identidad o ruta de un recurso, incluso borrado")
    impact.add_argument("--depth", type=int, help="profundidad máxima del recorrido")
    impact.add_argument("--json", action="store_true", help="alias compatible de --format json")
    impact.add_argument("--format", choices=("text", "json"), default="text")
    impact.add_argument("--root", type=Path, help="raíz del repositorio")
    impact.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")
    coverage = commands.add_parser("coverage", help="muestra qué ficheros aún no declaran ninguna identidad")
    coverage.add_argument("paths", nargs="*", type=Path, help="ficheros o directorios a resumir (por defecto, todo)")
    coverage.add_argument("--depth", type=int, default=1, help="niveles de directorio por los que agrupar (por defecto, 1)")
    coverage.add_argument("--files", action="store_true", help="lista cada fichero sin identidades")
    coverage.add_argument("--ext", action="append", metavar="EXT",
                          help="solo ficheros con esta extensión, por ejemplo --ext md (repetible)")
    coverage.add_argument("--repeated", action="store_true",
                          help="muestra solo las copias redundantes (sin el original) y cuánto se limpiaría")
    coverage.add_argument("--unique", action="store_true",
                          help="omite copias idénticas de un fichero ya marcado o listado antes")
    _query_options(coverage)
    dedupe = commands.add_parser("dedupe", help="borra copias idénticas de documentos y reapunta sus enlaces")
    dedupe.add_argument("paths", nargs="*", type=Path, help="limita a las copias bajo estas rutas")
    dedupe.add_argument("--ext", action="append", metavar="EXT",
                        help="extensiones a tratar (por defecto, md; los enlaces solo se reescriben en .md)")
    dedupe.add_argument("--apply", action="store_true",
                        help="reescribe enlaces y borra las copias; sin esto solo muestra el plan")
    dedupe.add_argument("--root", type=Path, help="raíz del repositorio")
    dedupe.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")
    listing = commands.add_parser("list", help="lista identidades del modelo")
    listing.add_argument("--type", dest="element_type", help="tipo semántico o estructural")
    listing.add_argument("--kind", help="kind de artifact o facet")
    listing.add_argument("--subject", help="subject declarado")
    _query_options(listing)
    for name, help_text in (("incoming", "muestra relaciones entrantes"),
                            ("outgoing", "muestra relaciones salientes")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("identity")
        command.add_argument("--relation", help="filtra por tipo de relación")
        _query_options(command)
    tree = commands.add_parser("tree", help="muestra estructura y ownership")
    tree.add_argument("identity")
    _query_options(tree)
    path = commands.add_parser("path", help="busca el camino semántico más corto")
    path.add_argument("source")
    path.add_argument("target")
    _query_options(path)
    query_command = commands.add_parser("query", help="lista o ejecuta queries Python registradas")
    query_command.add_argument("query_name", help="nombre de query, o 'list'")
    query_command.add_argument("query_arguments", nargs="*", help="argumentos posicionales de la query")
    _query_options(query_command)
    rule_command = commands.add_parser("rule", help="inspecciona reglas Python registradas")
    rule_command.add_argument("action", choices=("list",))
    _query_options(rule_command)
    return result


def _query_options(command) -> None:
    command.add_argument("--format", choices=("text", "json"), default="text")
    command.add_argument("--root", type=Path, help="raíz del repositorio")
    command.add_argument("--no-cache", action="store_true", help="ignora y no actualiza la caché")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = args.root.resolve() if args.root else find_repo_root(Path.cwd())
        paths = args.paths or None if args.command == "check" else None
        model = ModelBuilder(use_cache=not args.no_cache).build(root, paths)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "dedupe":
        return run_dedupe(root, model, args.paths, args.ext, args.apply)
    if args.command == "coverage" and args.repeated:
        return show_repeated(root, model, args.paths, args.depth, args.files, args.ext, args.format)
    if args.command == "coverage":
        return show_coverage(root, model, args.paths, args.depth, args.files, args.unique, args.ext, args.format)
    if args.command == "show":
        return show_identity(root, Graph(model), args.identity, args.format)
    if args.command == "impact":
        return show_impact(root, model, args.target, args.depth, args.json or args.format == "json")
    if args.command in {"list", "incoming", "outgoing", "tree", "path", "query", "rule"}:
        graph = Graph(model)
        if graph.resolution.diagnostics:
            return _invalid_graph(root, graph)
        try:
            if args.command == "list":
                return list_identities(root, graph, args.element_type, args.kind, args.subject, args.format)
            if args.command in {"incoming", "outgoing"}:
                return show_relations(root, graph, args.identity, args.command, args.relation, args.format)
            if args.command == "tree":
                return show_tree(root, graph, args.identity, args.format)
            if args.command == "query":
                return run_query(root, graph, args.query_name, tuple(args.query_arguments), args.format)
            if args.command == "rule":
                return show_rules(args.format)
            return show_path(graph, args.source, args.target, args.format)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    graph = Graph(model)
    diagnostics = list(graph.resolution.diagnostics)
    if not diagnostics:
        diagnostics.extend(CORE_RULES.run(graph, model.config.rules))
    for diagnostic in diagnostics:
        prefix = "warning: " if diagnostic.severity == "warning" else ""
        print(prefix + diagnostic.format(root))
    errors = [item for item in diagnostics if item.severity == "error"]
    if errors:
        print(f"FAIL: {len(errors)} error(es), {len(model.observations)} observaciones")
        return 1
    print(f"OK: {len(model.identities)} identidades, {len(model.observations)} observaciones "
          f"(cache: {model.cache_hits} reutilizados, {model.cache_misses} leídos)"
          f"{f', {len(diagnostics)} warning(s)' if diagnostics else ''}")
    return 0


def run_dedupe(root: Path, model, paths: list[Path], extensions: list[str] | None, apply: bool) -> int:
    suffixes = {"." + item.lstrip(".").lower() for item in extensions or ["md"]}
    plan = build_plan(root, file_coverage(model), paths, suffixes)
    rel = lambda path: path.relative_to(root).as_posix()
    for copy, original in plan.deletions:
        print(f"borrar {rel(copy)}  (queda {rel(original)})")
    for path, reason in plan.skipped:
        print(f"omitido {rel(path)}: {reason}")
    for rewrite in plan.rewrites:
        print(f"enlace {rel(rewrite.path)}:{rewrite.line}: {rewrite.old} -> {rewrite.new}")
    if plan.mentions:
        print("menciones sueltas que no se pueden reescribir (revisar a mano):")
        for mention in plan.mentions:
            print(f"  {rel(mention.path)}:{mention.line}: {mention.text[:100]}  [{mention.copy.name}]")
    files = len({rewrite.path for rewrite in plan.rewrites})
    print(f"{len(plan.deletions)} copias, {len(plan.rewrites)} enlaces en {files} ficheros, "
          f"{len(plan.mentions)} menciones sueltas")
    if not apply:
        print("vista previa: no se ha modificado nada; usa --apply para ejecutarlo")
        return 0
    try:
        apply_plan(plan)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("aplicado")
    return 0


def _select(root: Path, items, paths: list[Path], extensions: list[str] | None, key=lambda item: item):
    """Filtra por extensión y por rutas; `key` extrae el FileCoverage de cada elemento."""
    if extensions:
        suffixes = {"." + item.lstrip(".").lower() for item in extensions}
        items = [item for item in items if key(item).path.suffix.lower() in suffixes]
    if paths:
        selected = [(path if path.is_absolute() else root / path).resolve() for path in paths]
        items = [item for item in items if any(key(item).path.is_relative_to(path) for path in selected)]
    return items


def _group_name(root: Path, item, depth: int) -> str:
    parts = item.path.relative_to(root).parent.parts[:max(depth, 1)]
    return "/".join(parts) or "."


def show_repeated(root: Path, model, paths: list[Path], depth: int, list_files: bool,
                  extensions: list[str] | None, output_format: str) -> int:
    pairs = _select(root, repeated(file_coverage(model)), paths, extensions, key=lambda pair: pair[0])
    rel = lambda item: item.path.relative_to(root).as_posix()
    groups: dict[str, list[int]] = {}
    for copy, _ in pairs:
        counts = groups.setdefault(_group_name(root, copy, depth), [0, 0])
        counts[0] += 1
        counts[1] += copy.lines
    rows = sorted(groups.items(), key=lambda entry: (-entry[1][0], entry[0]))
    total_files = sum(counts[0] for counts in groups.values())
    total_lines = sum(counts[1] for counts in groups.values())

    if output_format == "json":
        print(json.dumps({
            "summary": [{"directory": name, "files": count, "lines": lines} for name, (count, lines) in rows],
            "total": {"files": total_files, "lines": total_lines},
            "repeated": [{"path": rel(copy), "lines": copy.lines, "copy_of": rel(original),
                          "traced": bool(copy.identities)} for copy, original in pairs],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"{total_files} ficheros repetidos, {total_lines} líneas que se podrían quitar")
    width = max((len(name) for name, _ in rows), default=1)
    for name, (count, lines) in rows:
        print(f"  {name:<{width}}  {count:>4} ficheros, {lines:>7} líneas")
    if list_files:
        print("repetidos (copia <- original):")
        for copy, original in pairs:
            flag = " [con identidades]" if copy.identities else ""
            print(f"  {rel(copy)} ({copy.lines} líneas) <- {rel(original)}{flag}")
    return 0


def show_coverage(root: Path, model, paths: list[Path], depth: int, list_files: bool,
                  unique: bool, extensions: list[str] | None, output_format: str) -> int:
    items = file_coverage(model)
    copies: dict[Path, list[Path]] = {}
    if unique:
        kept, copies = unique_untraced(items)
        keep = {item.path for item in kept}
        items = [item for item in items if item.identities or item.path in keep]
    items = _select(root, items, paths, extensions)

    def group(item) -> str:
        return _group_name(root, item, depth)

    groups: dict[str, list[int]] = {}
    for item in items:
        counts = groups.setdefault(group(item), [0, 0])
        counts[0] += 1
        counts[1] += bool(item.identities)
    untraced = sorted((item for item in items if not item.identities),
                      key=lambda item: (group(item), -item.lines, item.path))
    nested = [path.relative_to(root).as_posix()
              for path in ModelBuilder().nested_projects(root, model.config)]
    rows = sorted(groups.items(), key=lambda entry: (entry[1][1] - entry[1][0], entry[0]))

    if output_format == "json":
        print(json.dumps({
            "summary": [{"directory": name, "files": total, "traced": traced, "untraced": total - traced}
                        for name, (total, traced) in rows],
            "untraced": [{"path": item.path.relative_to(root).as_posix(), "lines": item.lines,
                          "copies": [path.relative_to(root).as_posix() for path in copies.get(item.path, ())]}
                         for item in untraced],
            "nested_projects": nested,
        }, ensure_ascii=False, indent=2))
        return 0

    total = sum(counts[0] for counts in groups.values())
    traced = sum(counts[1] for counts in groups.values())
    print(f"{traced}/{total} ficheros declaran alguna identidad ({len(untraced)} sin marcar)")
    width = max((len(name) for name, _ in rows), default=1)
    for name, (count, done) in rows:
        print(f"  {name:<{width}}  {done:>4}/{count:<4} marcados, {count - done:>4} sin marcar")
    if list_files:
        print("sin marcar (por directorio, más largos primero):")
        for item in untraced:
            extra = f", +{len(copies[item.path])} copias" if copies.get(item.path) else ""
            print(f"  {item.path.relative_to(root).as_posix()} ({item.lines} líneas{extra})")
            for copy in copies.get(item.path, ()):
                print(f"      = {copy.relative_to(root).as_posix()}")
    if nested:
        print("proyectos anidados (fuera de este análisis): " + ", ".join(nested))
    return 0


def _invalid_graph(root: Path, graph: Graph) -> int:
    for diagnostic in graph.resolution.diagnostics:
        print(diagnostic.format(root), file=sys.stderr)
    print("error: no se puede consultar un grafo inválido", file=sys.stderr)
    return 1


def list_identities(root: Path, graph: Graph, element_type, kind, subject, output_format: str) -> int:
    identities = graph.identities(element_type=element_type, kind=kind, subject=subject)
    if output_format == "json":
        print(json.dumps([_identity_json(item, root) for item in identities], ensure_ascii=False, indent=2))
    else:
        for identity in identities:
            description = identity.artifact_type if identity.element_type == "artifact" else identity.element_type
            print(f"{identity.key} [{description}] {identity.location.display(root)}")
    return 0


def show_relations(root: Path, graph: Graph, requested: str, direction: str,
                   relation_filter: str | None, output_format: str) -> int:
    relations = getattr(graph, direction)(requested, relation_filter)
    if output_format == "json":
        print(json.dumps([_relation_json(item, root) for item in relations], ensure_ascii=False, indent=2))
    elif not relations:
        print("sin relaciones")
    else:
        for relation in relations:
            print(f"{relation.source.key} --{relation.kind}--> {relation.target.key}")
    return 0


def show_tree(root: Path, graph: Graph, requested: str, output_format: str) -> int:
    identity = graph.one(requested)

    def node(item):
        return {**_identity_json(item, root), "children": [node(child) for child in graph.children(item.key)]}

    if output_format == "json":
        print(json.dumps(node(identity), ensure_ascii=False, indent=2))
        return 0

    def lines(item, prefix=""):
        result = [f"{prefix}{item.key} [{item.element_type}]"]
        children = graph.children(item.key)
        for index, child in enumerate(children):
            last = index == len(children) - 1
            branch = "\\-- " if last else "+-- "
            continuation = "    " if last else "|   "
            nested = lines(child, prefix + continuation)
            nested[0] = prefix + branch + nested[0].removeprefix(prefix + continuation)
            result.extend(nested)
        return result

    print("\n".join(lines(identity)))
    return 0


def show_path(graph: Graph, source: str, target: str, output_format: str) -> int:
    route = graph.shortest_path(source, target)
    if route is None:
        if output_format == "json":
            print(json.dumps({"source": source, "target": target, "path": None}, indent=2))
        else:
            print(f"sin camino entre {source} y {target}")
        return 1
    if output_format == "json":
        print(json.dumps({"source": source, "target": target, "path": [_hop_json(item) for item in route]},
                         ensure_ascii=False, indent=2))
    elif not route:
        print(source)
    else:
        print(_format_route(route))
    return 0


def run_query(root: Path, graph: Graph, name: str, arguments: tuple[str, ...], output_format: str) -> int:
    if name == "list":
        if arguments:
            raise ValueError("'trace query list' no acepta argumentos")
        definitions = sorted(CORE_QUERIES.definitions.values(), key=lambda item: item.name)
        if output_format == "json":
            print(json.dumps([{
                "name": item.name,
                "description": item.description,
                "arguments": list(item.arguments),
            } for item in definitions], ensure_ascii=False, indent=2))
        else:
            for item in definitions:
                signature = " ".join(f"<{argument}>" for argument in item.arguments)
                print(f"{item.name}{(' ' + signature) if signature else ''}: {item.description}")
        return 0
    result = CORE_QUERIES.run(name, graph, arguments)
    if output_format == "json":
        print(json.dumps({
            "query": result.query.name,
            "arguments": list(result.arguments),
            "matches": [{
                **_identity_json(match.identity, root),
                "reason": match.reason,
                "relations": [_relation_json(item, root) for item in match.relations],
            } for match in result.matches],
        }, ensure_ascii=False, indent=2))
    elif not result.matches:
        print("sin resultados")
    else:
        for match in result.matches:
            print(f"{match.identity.key}: {match.reason}")
    return 0


def show_rules(output_format: str) -> int:
    definitions = sorted(CORE_RULES.definitions.values(), key=lambda item: item.name)
    if output_format == "json":
        print(json.dumps([{
            "name": item.name, "description": item.description,
        } for item in definitions], ensure_ascii=False, indent=2))
    else:
        for item in definitions:
            print(f"{item.name}: {item.description}")
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
                "path": [_hop_json(hop) for hop in item.path],
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
        "artifactType": identity.artifact_type,
        "owner": identity.owner,
        "parentFacet": identity.parent_facet,
        "formal": identity.formal,
        "metadata": identity.metadata,
        "location": identity.location.display(root),
    }


def _relation_json(relation, root: Path) -> dict:
    return {
        "source": _identity_json(relation.source, root),
        "relation": relation.kind,
        "target": _identity_json(relation.target, root),
        "attributes": relation.attributes,
    }


def _hop_json(hop) -> dict:
    return {
        "from": hop.origin, "to": hop.destination,
        "relation": hop.relation, "direction": hop.direction,
    }


def _format_route(path) -> str:
    parts = [path[0].origin]
    for hop in path:
        if hop.direction == "outgoing":
            parts.append(f"--{hop.relation}--> {hop.destination}")
        else:
            parts.append(f"<--{hop.relation}-- {hop.destination}")
    return " ".join(parts)


def show_identity(root: Path, graph: Graph, requested: str, output_format: str) -> int:
    try:
        identity = graph.one(requested)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for item in graph.by_key.get(requested, ())[1:]:
            print(f"  {item.location.display(root)}", file=sys.stderr)
        return 1
    incoming = graph.incoming(requested)
    outgoing = graph.outgoing(requested)
    if output_format == "json":
        print(json.dumps({
            **_identity_json(identity, root),
            "incoming": [_relation_json(item, root) for item in incoming],
            "outgoing": [_relation_json(item, root) for item in outgoing],
        }, ensure_ascii=False, indent=2))
        return 0
    description = identity.artifact_type if identity.element_type == "artifact" else identity.element_type
    print(f"{identity.key} [{description}]")
    print(f"declarada en {identity.location.display(root)}")
    if identity.parent_facet:
        print(f"parent-facet: {identity.parent_facet}")
    connected = outgoing + incoming
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
