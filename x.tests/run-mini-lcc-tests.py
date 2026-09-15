#!/usr/bin/env python3
"""Genera casos desde y.lcc/mini-tst y los ejecuta con x.tests/run_tests.py."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
MINI_LCC = REPOSITORY / "y.lcc"
OUT_DIR = MINI_LCC / "mini-tst-out"
GENERATED = ROOT / "generated" / "mini-lcc"
XFAIL_RE = re.compile(r"/\*\s*xfail:\s*(.*?)\s*\*/", re.DOTALL)


def run(command: list[str], cwd: Path) -> int:
    print("$ " + " ".join(command), flush=True)
    return subprocess.call(command, cwd=str(cwd))


def generate_lcc_outputs(tests: list[str], simulate: bool) -> int:
    script = MINI_LCC / "run-mini-tst.py"
    if not script.exists():
        print("error: falta el submodulo y.lcc", file=sys.stderr)
        print("Inicializalo con: git submodule update --init --recursive y.lcc", file=sys.stderr)
        return 2
    (MINI_LCC / "build").mkdir(exist_ok=True)
    command = [sys.executable, str(script), *tests]
    if simulate:
        command.insert(2, "--simulate")
    return run(command, MINI_LCC)


def adapt_manifest(source: Path) -> Path:
    raw = json.loads(source.read_text(encoding="utf-8"))
    name = raw["name"]
    case_dir = GENERATED / name
    case_dir.mkdir(parents=True, exist_ok=True)

    binary = (MINI_LCC / raw["program"]).with_suffix(".bin")
    raw["program"] = os.path.relpath(binary, case_dir)
    for item in raw.get("initial_memory", []):
        item["file"] = os.path.relpath(MINI_LCC / item["file"], case_dir)
    for item in raw.get("expect", {}).get("memory_dumps", []):
        item["file"] = os.path.relpath(MINI_LCC / item["file"], case_dir)

    destination = case_dir / "test.json"
    destination.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return destination


def selected_manifests(tests: list[str]) -> list[Path]:
    manifests = sorted(OUT_DIR.glob("*.json"))
    if not tests:
        return manifests
    wanted = {Path(test).stem for test in tests}
    return [path for path in manifests if path.stem in wanted]


def is_xfail(manifest: Path) -> bool:
    source = MINI_LCC / "mini-tst" / f"{manifest.stem}.c"
    if not source.exists():
        return False
    return XFAIL_RE.search(source.read_text(encoding="utf-8")) is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="tests de mini-lcc por nombre o fichero .c")
    parser.add_argument("--backend", default="cpu-simulator",
                        choices=("cpu-simulator", "cpu-fpga", "both"))
    parser.add_argument("--version", action="append", default=[])
    parser.add_argument("--port")
    parser.add_argument("--simulate-lcc", action="store_true",
                        help="tambien ejecuta la simulacion propia de y.lcc al generar")
    parser.add_argument("--include-xfail", action="store_true",
                        help="incluye los xfail conocidos de mini-lcc como fallos normales de x.tests")
    parser.add_argument("--durations", type=int, nargs="?", const=10, default=0)
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args(argv)

    code = generate_lcc_outputs(args.tests, args.simulate_lcc)
    if code != 0:
        return code

    manifests = selected_manifests(args.tests)
    if not manifests:
        print("error: no se generaron manifiestos de mini-lcc", file=sys.stderr)
        return 2
    if not args.include_xfail:
        before = len(manifests)
        manifests = [path for path in manifests if not is_xfail(path)]
        skipped = before - len(manifests)
        if skipped:
            print(f"SKIP {skipped} xfail generados de mini-lcc")
    cases = [adapt_manifest(path) for path in manifests]

    command = [
        sys.executable,
        str(ROOT / "run_tests.py"),
        *map(str, cases),
        "--backend", args.backend,
    ]
    for version in args.version:
        command.extend(["--version", version])
    if args.port:
        command.extend(["--port", args.port])
    if args.durations:
        command.extend(["--durations", str(args.durations)])
    if args.yes:
        command.append("--yes")
    if args.no_upload:
        command.append("--no-upload")
    return run(command, ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
