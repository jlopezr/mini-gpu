#!/usr/bin/env python3
"""Recopila el informe de un prototipo: síntesis, capacidades y mapa de memoria."""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prototype import PrototypeResolutionError, find_repo_root, resolve_prototype


def _readme_title(prototype_dir: Path) -> str:
    readme = prototype_dir / "README.md"
    if not readme.exists():
        return ""
    for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^#\s+(.*)", line)
        if match:
            return match.group(1).strip()
    return ""


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
    return data


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
    """Como ast.literal_eval, pero también acepta `Path("...")` como si fuera
    el literal de su argumento (VERSIONS declara monitor_path con Path(...))."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(elt) for elt in node.elts)
    if isinstance(node, ast.List):
        return [_safe_eval(elt) for elt in node.elts]
    if isinstance(node, ast.Dict):
        return {_safe_eval(k): _safe_eval(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and len(node.args) == 1:
        return _safe_eval(node.args[0])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_eval(node.operand)
    raise ValueError(f"nodo no soportado: {ast.dump(node)}")


def _version_label(prototype_dir: Path, root: Path) -> dict:
    """Busca en x.tests/backends/{fpga,gpu_fpga}.py el nombre corto de versión
    (el que usa `run_tests.py --version`) y la descripción, si están
    registrados ahí. Es lo único que de verdad no se puede sacar del RTL: es
    una etiqueta elegida a mano, no un hecho verificable en el código."""
    backends_dir = root / "x.tests" / "backends"
    for module_name in ("fpga", "gpu_fpga"):
        module_path = backends_dir / f"{module_name}.py"
        if not module_path.exists():
            continue
        source = module_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(module_path))
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "VERSIONS"):
                continue
            try:
                versions = _safe_eval(node.value)
            except ValueError:
                continue
            for version_name, config in versions.items():
                monitor_path = config.get("monitor_path")
                if monitor_path and Path(monitor_path).parts[0] == prototype_dir.name:
                    return {"version_name": version_name, "description": config.get("description", "")}
    return {}


def _backend_from_rtl(prototype_dir: Path) -> str | None:
    """CPU o GPU no es una etiqueta: es qué módulo de núcleo hay en la
    carpeta. Nada que registrar en ningún sitio."""
    if (prototype_dir / "cpu.v").exists():
        return "cpu"
    if (prototype_dir / "gpu_sm.v").exists() or (prototype_dir / "gpu_system.v").exists():
        return "gpu"
    return None


def _monitor_version_from_rtl(prototype_dir: Path) -> tuple[int, int] | None:
    """VERSION_MAJOR/VERSION_MINOR son localparams reales en monitor.v: es lo
    que la placa responde de verdad a GET_VERSION, no una copia a mano."""
    monitor_v = prototype_dir / "monitor.v"
    if not monitor_v.exists():
        return None
    text = monitor_v.read_text(encoding="utf-8", errors="replace")
    major = re.search(r"VERSION_MAJOR\s*=\s*8'h([0-9a-fA-F]+)", text)
    minor = re.search(r"VERSION_MINOR\s*=\s*8'h([0-9a-fA-F]+)", text)
    if not major or not minor:
        return None
    return (int(major.group(1), 16), int(minor.group(1), 16))


def _clock_hz_from_rtl(prototype_dir: Path) -> int | None:
    """FREQUENCY_PIN_CLKOP es el atributo que nextpnr usa de verdad para
    timing, en el fichero del PLL (su nombre varía: pll_120.v, pll_cpu.v...)."""
    for pll_file in sorted(prototype_dir.glob("pll*.v")):
        text = pll_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'FREQUENCY_PIN_CLKOP\s*=\s*"(\d+(?:\.\d+)?)"', text)
        if match:
            return int(float(match.group(1)) * 1_000_000)
    return None


def _load_capability_signals(root: Path) -> dict:
    signals_path = root / "tools" / "capabilities.json"
    if not signals_path.exists():
        return {}
    data = json.loads(signals_path.read_text(encoding="utf-8"))
    return {name: spec for name, spec in data.items() if not name.startswith("_")}


def _capabilities_from_rtl(prototype_dir: Path, signals: dict) -> tuple[str, ...]:
    found = []
    for name, spec in signals.items():
        target = prototype_dir / spec["file"]
        if not target.exists():
            continue
        pattern = spec.get("pattern")
        if pattern is None or re.search(pattern, target.read_text(encoding="utf-8", errors="replace")):
            found.append(name)
    return tuple(found)


def _capabilities(prototype_dir: Path, root: Path) -> dict:
    """Identidad de un prototipo: backend/versión/clock/capacidades, leídos
    del RTL directamente en vez de copiados a mano en ningún sitio. Solo
    `version_name`/`description` (etiquetas humanas, no hechos verificables)
    se buscan en x.tests/backends/, y son opcionales."""
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
    result.update(_version_label(prototype_dir, root))
    result.setdefault("version_name", prototype_dir.name)
    return result


def collect(prototype_dir: Path, root: Path) -> dict:
    summary = _latest_summary(prototype_dir)
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
