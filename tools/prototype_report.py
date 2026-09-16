#!/usr/bin/env python3
"""Recopila el informe de un prototipo: síntesis, capacidades y mapa de memoria."""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prototype import PrototypeResolutionError, find_repo_root, resolve_prototype
from tools.rtl_facts import (
    backend_from_rtl as _backend_from_rtl,
    capabilities_from_rtl as _capabilities_from_rtl,
    clock_hz_from_rtl as _clock_hz_from_rtl,
    load_capability_signals as _load_capability_signals,
    monitor_version_from_rtl as _monitor_version_from_rtl,
    readme_title as _readme_title,
    uart_baud_from_rtl as _uart_baud_from_rtl,
)


def _git_info(prototype_dir: Path, root: Path) -> dict:
    try:
        rel = prototype_dir.relative_to(root)
    except ValueError:
        rel = prototype_dir
    try:
        output = subprocess.run(
            ["git", "log", "-1", "--format=%H%x1f%ad%x1f%s", "--date=short", "--", str(rel)],
            cwd=str(root), capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    if not output:
        return {}
    commit, date, subject = output.split("\x1f", 2)
    return {"commit": commit, "date": date, "subject": subject}


def _latest_summary(prototype_dir: Path) -> dict:
    history = prototype_dir / "reports"
    if not history.exists():
        return {}
    candidates = sorted(
        (d for d in history.iterdir() if (d / "summary.json").exists()),
        key=lambda d: d.name, reverse=True,
    )
    if not candidates:
        return {}
    data = json.loads((candidates[0] / "summary.json").read_text(encoding="utf-8"))
    data["_report_dir"] = str(candidates[0])
    data["_source"] = "reports"
    return data


def _build_snapshot(prototype_dir: Path) -> dict:
    """La última síntesis que hay en `_build/`, cuando no se archivó informe.

    `hardware.pnr` es lo que deja nextpnr y tiene la misma forma que el
    `summary.json` archivado, solo que llama `fmax` a lo que allí es `clocks`.
    Es dato local y no versionado -- `_build/` está en `.gitignore` --, así que
    solo se usa como respaldo: un informe archivado siempre gana.
    """
    builds = sorted(
        prototype_dir.glob("_build/*/hardware.pnr"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not builds:
        return {}
    data = json.loads(builds[0].read_text(encoding="utf-8"))
    return {
        "clocks": data.get("fmax", {}),
        "utilization": data.get("utilization", {}),
        "paths": data.get("critical_paths", []),
        "label": builds[0].parent.name,
        "_report_dir": str(builds[0].parent),
        "_source": "_build",
    }


def _memory_regions(prototype_dir: Path) -> dict:
    """Extrae ARCHITECTURAL_REGIONS/MONITOR_REGIONS de monitor.py sin importarlo
    (evita depender de pyserial solo para leer un informe)."""
    monitor = prototype_dir / "monitor.py"
    if not monitor.exists():
        return {}
    source = monitor.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(monitor))
    regions: dict[str, list] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name not in ("ARCHITECTURAL_REGIONS", "MONITOR_REGIONS"):
            continue
        try:
            regions[name] = _safe_eval(node.value)
        except ValueError:
            continue
    return regions


def _safe_eval(node: ast.AST):
    """Como ast.literal_eval, para leer ARCHITECTURAL_REGIONS/MONITOR_REGIONS
    de monitor.py sin importarlo."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(elt) for elt in node.elts)
    if isinstance(node, ast.List):
        return [_safe_eval(elt) for elt in node.elts]
    if isinstance(node, ast.Dict):
        return {_safe_eval(k): _safe_eval(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_eval(node.operand)
    raise ValueError(f"nodo no soportado: {ast.dump(node)}")


def _version_label(prototype_dir: Path, root: Path) -> dict:
    """El alias corto (el que usa `run_tests.py --version`) vive en
    `version.json`, dentro de la propia carpeta del prototipo. Es lo único que
    de verdad no se puede sacar de ningún sitio: es una etiqueta elegida a
    mano, no un hecho verificable -- y su ausencia también es información: un
    prototipo con RTL pero sin `version.json` no es un target de test
    soportado (ver `17.fpga-gpu-ram-v2`).

    La descripción, en cambio, por defecto es el título del README --
    `version.json` solo hace falta cuando ese título no basta y hay que
    sobreescribirlo con algo más técnico (ver `10.fpga-cpu-ram/version.json`).
    """
    del root  # Ya no hace falta: no se busca fuera de la carpeta del prototipo.
    manifest = prototype_dir / "version.json"
    if not manifest.exists():
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    description = data.get("description") or _readme_title(prototype_dir)
    result = {"version_name": data["alias"]}
    if description:
        result["description"] = description
    return result


def _capabilities(prototype_dir: Path, root: Path) -> dict:
    """Identidad de un prototipo: backend/versión/clock/capacidades, leídos
    del RTL directamente en vez de copiados a mano en ningún sitio. Solo
    `version_name`/`description` (etiquetas humanas, no hechos verificables)
    se buscan en `version.json`, y son opcionales."""
    backend = _backend_from_rtl(prototype_dir)
    if backend is None:
        return {}
    monitor_version = _monitor_version_from_rtl(prototype_dir)
    if monitor_version is None:
        return {}
    result = {
        "backend": backend,
        "monitor_version": monitor_version,
        "capabilities": _capabilities_from_rtl(prototype_dir, _load_capability_signals(root)),
    }
    clock_hz = _clock_hz_from_rtl(prototype_dir)
    if clock_hz is not None:
        result["clock_hz"] = clock_hz
    baud = _uart_baud_from_rtl(prototype_dir)
    if baud is not None:
        result["uart_baud"] = baud
    result.update(_version_label(prototype_dir, root))
    result.setdefault("version_name", prototype_dir.name)
    return result


_SIMULATOR_BACKENDS = (("cpu", "simulator.py"), ("gpu", "gpu_simulator.py"))


def _simulator_entry(node: ast.Dict, architecture: str) -> dict:
    """Una entrada del `VERSIONS` de un backend de simulador."""
    entry = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant):
            continue
        if key.value == "simulator_path":
            # `Path("2.cpu-sim-func/minicpu_sim.py")`: la carpeta es el nombre
            # con el que el prototipo aparece en el resto de informes.
            if isinstance(value, ast.Call) and value.args:
                argument = value.args[0]
                if isinstance(argument, ast.Constant):
                    entry["name"] = str(argument.value).split("/")[0]
        elif key.value in ("capabilities", "description"):
            try:
                entry[key.value] = _safe_eval(value)
            except ValueError:
                continue
    if "name" not in entry:
        return {}
    entry.setdefault("capabilities", ())
    entry["architecture"] = architecture
    return entry


def simulator_capabilities(root: Path) -> list[dict]:
    """Capacidades que declaran los backends de simulador.

    No se leen del fuente del simulador como se hace con el RTL, y no es un
    descuido: `minicpu_sim.py` despacha por opcode numérico (`if opcode ==
    0x2C:  # JAL`) y los mnemónicos solo viven en comentarios -- justo lo que
    `capabilities_from_rtl` se cuida de no dar por bueno. Aquí la declaración
    del backend es la fuente, y no puede pudrirse en silencio porque
    `incompatibility()` la usa para decidir qué casos corren.

    Se parsea con `ast` en vez de importar, por lo mismo que `_memory_regions`:
    para no arrastrar dependencias del runner solo para escribir un informe.
    """
    results = []
    for architecture, filename in _SIMULATOR_BACKENDS:
        path = root / "x.tests" / "backends" / filename
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id != "VERSIONS":
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for value in node.value.values:
                if isinstance(value, ast.Dict):
                    entry = _simulator_entry(value, architecture)
                    if entry:
                        results.append(entry)
    return results


def collect(prototype_dir: Path, root: Path) -> dict:
    summary = _latest_summary(prototype_dir) or _build_snapshot(prototype_dir)
    return {
        "name": prototype_dir.name,
        "title": _readme_title(prototype_dir),
        "git": _git_info(prototype_dir, root),
        "synthesis": summary,
        "capabilities": _capabilities(prototype_dir, root),
        "memory": _memory_regions(prototype_dir),
    }


def _fmt_region(region: tuple) -> str:
    start, end = region[0], region[1]
    label = region[2] if len(region) > 2 else ""
    size = end - start
    text = f"0x{start:08X}-0x{end:08X} ({size:,} bytes)"
    return f"{text} {label}".strip()


def format_text(report: dict) -> str:
    lines = [f"Prototype: {report['name']}"]
    if report["title"]:
        lines.append(f"Title: {report['title']}")

    git = report["git"]
    if git:
        lines.append(f"Last commit: {git['commit'][:10]} ({git['date']}) {git['subject']}")
    else:
        lines.append("Last commit: (sin historial de git para esta carpeta)")

    cap = report["capabilities"]
    if cap:
        lines.append(f"Backend: {cap['backend']} — {cap['version_name']} "
                     f"(monitor {'.'.join(map(str, cap.get('monitor_version', ())))})")
        if cap.get("description"):
            lines.append(f"Description: {cap['description']}")
        if cap.get("clock_hz"):
            lines.append(f"Clock: {cap['clock_hz'] / 1e6:.1f} MHz")
        lines.append(f"Capabilities: {', '.join(cap.get('capabilities', ())) or '(ninguna detectada)'}")
    else:
        lines.append("Capabilities: (no tiene cpu.v/gpu_sm.v/gpu_system.v + monitor.v con versión: no es un núcleo)")

    mem = report["memory"]
    if mem:
        lines.append("Memory map:")
        for name, regions in mem.items():
            lines.append(f"  {name}:")
            for region in regions:
                lines.append(f"    {_fmt_region(region)}")
    else:
        lines.append("Memory map: (no se encontró monitor.py con ARCHITECTURAL_REGIONS)")

    synth = report["synthesis"]
    if synth:
        lines.append(f"Synthesis (label={synth.get('label')}, {synth.get('_report_dir')}):")
        for clock, values in synth.get("clocks", {}).items():
            achieved, constraint = values.get("achieved"), values.get("constraint")
            status = "PASS" if achieved is not None and constraint is not None and achieved >= constraint else "FAIL"
            lines.append(f"  {clock}: {achieved:.2f} / {constraint:.2f} MHz [{status}]")
        for name, values in synth.get("utilization", {}).items():
            lines.append(f"  {name}: {values.get('used')} / {values.get('available')}")
    else:
        lines.append("Synthesis: (sin reports/*/summary.json; ejecuta ./build --report)")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--prototype", required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve() if args.root else find_repo_root(Path.cwd())
    try:
        prototype_dir = resolve_prototype(args.prototype, root=root)
    except PrototypeResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = collect(prototype_dir, root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
