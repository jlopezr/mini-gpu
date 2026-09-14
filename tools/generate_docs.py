#!/usr/bin/env python3
"""Genera docs/synthesis-report.md y docs/capabilities.md a partir de
prototype_report.collect(); actualiza bloques marcados en documentación
manual (docs/resumen-prototipos.md, docs/mapa-de-memoria.md) solo si ya existen, para no
sobrescribir texto escrito a mano."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prototype import find_repo_root, list_prototypes
from tools.prototype_report import collect

MARKER_RE_TEMPLATE = "<!-- {tag} GENERATED: {name} -->"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="no escribe; indica si algo cambiaría")
    args = parser.parse_args()

    root = args.root.resolve() if args.root else find_repo_root(Path.cwd())
    reports = build_reports(root)

    changed = False

    capabilities_doc = render_dedicated_doc(
        "Capacidades declaradas por prototipo", "capabilities-table", _capabilities_table(reports)
    )
    if write_if_changed(root / "docs" / "capabilities.md", capabilities_doc, args.check):
        changed = True
        print(f"{'(check) cambiaría' if args.check else 'escrito'}: docs/capabilities.md")
    else:
        print("ok: docs/capabilities.md ya estaba al día")

    synthesis_doc = render_dedicated_doc(
        "Último informe de síntesis por prototipo", "synthesis-table", _synthesis_table(reports)
    )
    if write_if_changed(root / "docs" / "synthesis-report.md", synthesis_doc, args.check):
        changed = True
        print(f"{'(check) cambiaría' if args.check else 'escrito'}: docs/synthesis-report.md")
    else:
        print("ok: docs/synthesis-report.md ya estaba al día")

    for path, marker_name, body in (
        (root / "docs/resumen-prototipos.md", "prototype-summary", _capabilities_table(reports)),
        (root / "docs/mapa-de-memoria.md", "prototype-summary", _capabilities_table(reports)),
    ):
        message = update_manual_doc(path, marker_name, body, args.check)
        print(message)
        if message.startswith("actualizado") or message.startswith("(check) cambiaría"):
            changed = True

    if args.check:
        return 1 if changed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
