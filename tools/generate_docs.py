#!/usr/bin/env python3
"""Genera docs/synthesis-report.md a partir de prototype_report.collect();
actualiza bloques marcados en documentación manual (las matrices de CPU y GPU
y la tabla plana de docs/resumen-prototipos.md) solo si ya
existen, para no sobrescribir texto escrito a mano."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prototype import find_repo_root, list_prototypes
from tools.prototype_report import collect, simulator_capabilities
from tools.rtl_facts import load_capability_signals
from tools.traceability import (
    CORE_GENERATORS, GenerationContext, Graph, ModelBuilder, generator,
)

MARKER_RE_TEMPLATE = "<!-- {tag} GENERATED: {name} -->"
TRACE_BEGIN = re.compile(r"<!--\s*gendoc:begin\s+([A-Za-z0-9_-]+)\s*\n(.*?)\n-->", re.DOTALL)
MARKDOWN_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})", re.MULTILINE)


# @artifact IMPL-GENDOC type=implementation
def marker_block(name: str, body: str) -> str:
    begin = MARKER_RE_TEMPLATE.format(tag="BEGIN", name=name)
    end = MARKER_RE_TEMPLATE.format(tag="END", name=name)
    return f"{begin}\n{body}\n{end}"


def update_marked_block(text: str, name: str, body: str) -> tuple[str, bool]:
    """Reemplaza el contenido entre BEGIN/END GENERATED: name. Devuelve
    (texto, encontrado). Si no encuentra los marcadores, no toca el texto."""
    begin = MARKER_RE_TEMPLATE.format(tag="BEGIN", name=name)
    end = MARKER_RE_TEMPLATE.format(tag="END", name=name)
    start_idx = text.find(begin)
    end_idx = text.find(end)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return text, False
    new_text = text[:start_idx] + begin + "\n" + body + "\n" + end + text[end_idx + len(end):]
    return new_text, True


# @id capabilities-table
def _capabilities_table(reports: list[dict]) -> str:
    rows = [r for r in reports if r["capabilities"]]
    if not rows:
        return "_Ningún prototipo tiene capacidades declaradas en `x.tests/backends/`._"
    lines = [
        "| Prototype | Version | Monitor | Clock | Capabilities |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        cap = r["capabilities"]
        monitor = ".".join(map(str, cap.get("monitor_version", ())))
        clock = f"{cap['clock_hz'] / 1e6:.1f} MHz" if cap.get("clock_hz") else "—"
        caps = ", ".join(cap.get("capabilities", ())) or "—"
        lines.append(f"| [`{r['name']}`](../{r['name']}) | {cap['version_name']} | {monitor} | {clock} | {caps} |")
    return "\n".join(lines)


def _humanize_bytes(size: int) -> str:
    for unit, scale in (("MiB", 1 << 20), ("KiB", 1 << 10)):
        if size >= scale and size % scale == 0:
            return f"{size // scale} {unit}"
    return f"{size} B"


def _memory_cell(report: dict) -> str:
    regions = report.get("memory", {}).get("ARCHITECTURAL_REGIONS") or ()
    sizes = [end - start for start, end, *_ in regions]
    if not sizes:
        return "—"
    if len(sizes) == 1:
        return _humanize_bytes(sizes[0])
    if len(set(sizes)) == 1:
        return f"{len(sizes)} × {_humanize_bytes(sizes[0])}"
    return " + ".join(_humanize_bytes(size) for size in sizes)


def _fmax_cell(report: dict) -> str:
    """El dominio con menos margen, que es el que decide si el diseño cierra.

    Un prototipo puede tener varios relojes -la 22 tiene tres- y quedarse con
    el más rápido diría lo contrario de lo que importa. El desglose completo
    está en `docs/synthesis-report.md`."""
    clocks = report.get("synthesis", {}).get("clocks") or {}
    usable = [
        (values["achieved"], values["constraint"])
        for values in clocks.values()
        if values.get("achieved") is not None and values.get("constraint")
    ]
    if not usable:
        return "—"
    achieved, constraint = min(usable, key=lambda pair: pair[0] / pair[1])
    return f"{achieved:.1f} / {constraint:.0f}"


def _utilization_cell(report: dict) -> str:
    used = report.get("synthesis", {}).get("utilization") or {}
    luts = used.get("TRELLIS_COMB", {}).get("used")
    flops = used.get("TRELLIS_FF", {}).get("used")
    if luts is None or flops is None:
        return "—"
    return f"{luts:,} / {flops:,}".replace(",", " ")


def _baud_cell(baud) -> str:
    if not baud:
        return "—"
    if baud % 1_000_000 == 0:
        return f"{baud // 1_000_000} M"
    if baud % 1_000 == 0:
        return f"{baud // 1_000} k"
    return str(baud)


def _column_label(name: str, version_name: str) -> str:
    """`6.ebr`, `10.sdram`: el número de la carpeta con el alias corto. Si no
    hay alias -- la 17 no tiene `version.json` -- se queda el nombre entero."""
    number = name.split(".", 1)[0]
    if version_name and version_name != name:
        return f"{number}.{version_name}"
    return name


def _expand_implies(names, signals: dict) -> frozenset:
    """`frame_capture` implica `video`: el backend declara solo la primera y
    `expand_capabilities` hace el resto en el runner. La detección por RTL no
    lo necesita -- encuentra las dos cuando comparten `file`."""
    expanded = set(names)
    for name in tuple(expanded):
        expanded.update(signals.get(name, {}).get("implies", ()))
    return frozenset(expanded)


# @id capability-matrix
def _matrix_table(reports: list[dict], simulators: list[dict], signals: dict,
                  architecture: str) -> str:
    columns = []
    for entry in simulators:
        if entry["architecture"] == architecture:
            number = entry["name"].split(".", 1)[0]
            columns.append({
                "label": f"{number}.sim", "path": entry["name"],
                "capabilities": _expand_implies(entry.get("capabilities", ()), signals),
                "hardware": None,
            })
    for report in reports:
        cap = report["capabilities"]
        if not cap or cap.get("backend") != architecture:
            continue
        columns.append({
            "label": _column_label(report["name"], cap.get("version_name", "")),
            "path": report["name"],
            "capabilities": frozenset(cap.get("capabilities", ())),
            "hardware": report,
            "monitor": ".".join(map(str, cap.get("monitor_version", ()))),
            "clock_hz": cap.get("clock_hz"),
            "uart_baud": cap.get("uart_baud"),
        })
    if not columns:
        return f"_Ningún prototipo declara arquitectura `{architecture}`._"

    header = "| | " + " | ".join(
        f"[{column['label']}](../{column['path']})" for column in columns
    ) + " |"
    lines = [header, "|---|" + "---|" * len(columns)]

    def row(title: str, cell) -> None:
        lines.append(f"| **{title}** | " + " | ".join(cell(c) for c in columns) + " |")

    row("Reloj", lambda c: f"{c['clock_hz'] / 1e6:.0f} MHz" if c.get("clock_hz") else "—")
    row("Fmax / objetivo", lambda c: _fmax_cell(c["hardware"]) if c["hardware"] else "—")
    row("Memoria", lambda c: _memory_cell(c["hardware"]) if c["hardware"] else "—")
    row("LUT / FF", lambda c: _utilization_cell(c["hardware"]) if c["hardware"] else "—")
    row("Monitor", lambda c: c.get("monitor") or "—")
    row("Baudios", lambda c: _baud_cell(c.get("uart_baud")))

    for capability, spec in signals.items():
        if spec.get("architecture") != architecture:
            continue
        lines.append(
            f"| `{capability}` | "
            + " | ".join("sí" if capability in c["capabilities"] else "no" for c in columns)
            + " |"
        )
    return "\n".join(lines)


# @id synthesis-table
def _synthesis_table(reports: list[dict]) -> str:
    rows = [r for r in reports if r["synthesis"]]
    if not rows:
        return "_Ningún prototipo tiene un `reports/*/summary.json` archivado todavía._"
    lines = [
        "| Prototype | Label | Clock | Achieved / Target (MHz) | Status |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        synth = r["synthesis"]
        for clock, values in synth.get("clocks", {}).items():
            achieved, constraint = values.get("achieved"), values.get("constraint")
            status = "PASS" if achieved is not None and constraint is not None and achieved >= constraint else "FAIL"
            lines.append(
                f"| [`{r['name']}`](../{r['name']}) | {synth.get('label', '')} | {clock} | "
                f"{achieved:.2f} / {constraint:.2f} | {status} |"
            )
    return "\n".join(lines)


def build_reports(root: Path) -> list[dict]:
    return [collect(prototype_dir, root) for prototype_dir in list_prototypes(root)]


def render_dedicated_doc(title: str, marker_name: str, body: str) -> str:
    header = f"# {title}\n\n_Generado por `generate-docs` a partir de `x.tests/backends/` y `reports/`. No editar a mano: los cambios se perderán._\n\n"
    return header + marker_block(marker_name, body) + "\n"


def write_if_changed(path: Path, content: str, check: bool) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    if check:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def update_manual_doc(path: Path, marker_name: str, body: str, check: bool) -> str:
    if not path.exists():
        return f"skip: {path.name} no existe"
    text = path.read_text(encoding="utf-8")
    new_text, found = update_marked_block(text, marker_name, body)
    if not found:
        return (
            f"skip: {path.name} no tiene <!-- BEGIN GENERATED: {marker_name} --> ... "
            f"<!-- END GENERATED: {marker_name} -->; añádelo a mano donde quieras la tabla generada"
        )
    if new_text == text:
        return f"ok: {path.name} ya estaba al día"
    if not check:
        path.write_text(new_text, encoding="utf-8")
    return f"{'(check) cambiaría' if check else 'actualizado'}: {path.name}"


# @id trace-query
def update_generated_blocks(text: str, context: GenerationContext) -> tuple[str, int]:
    """Materializa bloques gendoc mediante el GeneratorRegistry."""
    output = []
    cursor = 0
    changed = 0
    fenced = _fenced_ranges(text)
    search_from = 0
    while match := TRACE_BEGIN.search(text, search_from):
        if any(start <= match.start() < end for start, end in fenced):
            search_from = match.end()
            continue
        name = match.group(1)
        end_marker = f"<!-- gendoc:end {name} -->"
        end = text.find(end_marker, match.end())
        if end < 0:
            raise ValueError(f"bloque gendoc '{name}' sin cierre")
        metadata = yaml.safe_load(match.group(2)) or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"metadata inválida en bloque gendoc '{name}'")
        output.append(text[cursor:match.end()])
        generator_name = metadata.pop("generator", None)
        if not isinstance(generator_name, str):
            raise ValueError(f"bloque gendoc '{name}' requiere generator")
        body = CORE_GENERATORS.run(generator_name, context, metadata)
        replacement = f"\n\n{body}\n\n{end_marker}"
        original = text[match.end():end + len(end_marker)]
        changed += replacement != original
        output.append(replacement)
        cursor = end + len(end_marker)
        search_from = cursor
    output.append(text[cursor:])
    return "".join(output), changed


def update_trace_query_blocks(text: str, graph: Graph) -> tuple[str, int]:
    """Compatibilidad interna para callers del primer slice de gendoc."""
    return update_generated_blocks(text, GenerationContext(graph.model.root, graph))


def _fenced_ranges(text: str) -> list[tuple[int, int]]:
    result = []
    opened = None
    marker = None
    for match in MARKDOWN_FENCE.finditer(text):
        current = match.group(1)
        if opened is None:
            opened, marker = match.start(), current[0]
        elif current[0] == marker:
            line_end = text.find("\n", match.end())
            result.append((opened, len(text) if line_end < 0 else line_end + 1))
            opened = marker = None
    if opened is not None:
        result.append((opened, len(text)))
    return result


@generator("prototype-summary", description="Tabla resumen de capacidades por prototipo")
def generate_prototype_summary(context: GenerationContext, options: dict) -> str:
    return _capabilities_table(context.values["reports"])


@generator("cpu-matrix", description="Matriz de capacidades de MiniCPU")
def generate_cpu_matrix(context: GenerationContext, options: dict) -> str:
    return _matrix_table(
        context.values["reports"], context.values["simulators"], context.values["signals"], "cpu"
    )


@generator("gpu-matrix", description="Matriz de capacidades de MiniGPU")
def generate_gpu_matrix(context: GenerationContext, options: dict) -> str:
    return _matrix_table(
        context.values["reports"], context.values["simulators"], context.values["signals"], "gpu"
    )


@generator("synthesis-table", description="Últimos resultados de síntesis")
def generate_synthesis_table(context: GenerationContext, options: dict) -> str:
    return _synthesis_table(context.values["reports"])


def update_trace_docs(root: Path, check: bool) -> tuple[bool, list[str]]:
    model = ModelBuilder().build(root)
    graph = Graph(model)
    if graph.resolution.diagnostics:
        details = "; ".join(item.format(root) for item in graph.resolution.diagnostics)
        raise ValueError(f"grafo de trazabilidad inválido: {details}")
    changed = False
    messages = []
    context = GenerationContext(root, graph)
    for resource in model.resources:
        path = resource.path
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        if "gendoc:begin" not in text:
            continue
        rendered, replacements = update_generated_blocks(text, context)
        if not replacements:
            continue
        relative = path.relative_to(root).as_posix()
        changed = True
        messages.append(f"{'(check) cambiaría' if check else 'actualizado'}: {relative}")
        if not check:
            path.write_text(rendered, encoding="utf-8")
    return changed, messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="no escribe; indica si algo cambiaría")
    args = parser.parse_args()

    root = args.root.resolve() if args.root else find_repo_root(Path.cwd())
    reports = build_reports(root)
    simulators = simulator_capabilities(root)
    signals = load_capability_signals(root)
    generation = GenerationContext(root, values={
        "reports": reports, "simulators": simulators, "signals": signals,
    })

    changed = False

    synthesis_doc = render_dedicated_doc(
        "Último informe de síntesis por prototipo", "synthesis-table",
        CORE_GENERATORS.run("synthesis-table", generation),
    )
    if write_if_changed(root / "docs" / "synthesis-report.md", synthesis_doc, args.check):
        changed = True
        print(f"{'(check) cambiaría' if args.check else 'escrito'}: docs/synthesis-report.md")
    else:
        print("ok: docs/synthesis-report.md ya estaba al día")

    for path, marker_name, body in (
        (root / "docs/resumen-prototipos.md", "cpu-matrix",
         CORE_GENERATORS.run("cpu-matrix", generation)),
        (root / "docs/resumen-prototipos.md", "gpu-matrix",
         CORE_GENERATORS.run("gpu-matrix", generation)),
        (root / "docs/resumen-prototipos.md", "prototype-summary",
         CORE_GENERATORS.run("prototype-summary", generation)),
    ):
        message = update_manual_doc(path, marker_name, body, args.check)
        print(message)
        if message.startswith("actualizado") or message.startswith("(check) cambiaría"):
            changed = True

    try:
        trace_changed, messages = update_trace_docs(root, args.check)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    changed |= trace_changed
    for message in messages:
        print(message)

    if args.check:
        return 1 if changed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
