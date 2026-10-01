#!/usr/bin/env python3
"""Mide las suites del repositorio y escribe un informe ordenado por duración."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "x.tests"))

from tools import stage_programs  # noqa: E402
from tools.prototype import (  # noqa: E402
    PrototypeResolutionError, find_apio_binary, resolve_prototype,
)
from tools.test_runner import fixtures_step, slow_testbenches, testbenches  # noqa: E402


def newest_board_prototype(family: str) -> str:
    """Número del prototipo más reciente registrado para una familia de placa."""
    from tools.bench_all import prototypes

    candidates = prototypes(family)
    if not candidates:
        raise ValueError(f"no hay prototipos de placa para {family}")
    return str(max(candidates, key=lambda item: item[1])[1])


def detected_board_port() -> str | None:
    """Puerto FTDI, o None si no hay placa; la ambigüedad sigue siendo un error."""
    from backends import board

    try:
        return board.detect_port()
    except SystemExit as exc:
        # detect_port distingue ya entre cero y varios FTDI. Solo la ausencia
        # es el caso opcional del hardware automático; varios exige que el usuario
        # elija un puerto y no se debe convertir silenciosamente en "ninguno".
        if "no se encontró ningún adaptador FTDI" in str(exc):
            return None
        raise


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._failed_ids = set()
        self._skipped_ids = set()

    def startTest(self, test):
        self._test_started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        state = ("FALLO" if test.id() in self._failed_ids else
                 "SKIP" if test.id() in self._skipped_ids else "OK")
        self.timings.append({"name": test.id(), "seconds": time.perf_counter() - self._test_started,
                             "state": state})
        super().stopTest(test)

    def addFailure(self, test, err):
        self._failed_ids.add(test.id())
        super().addFailure(test, err)

    def addError(self, test, err):
        self._failed_ids.add(test.id())
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self._failed_ids.add(test.id())
        super().addSubTest(test, subtest, err)

    def addSkip(self, test, reason):
        self._skipped_ids.add(test.id())
        super().addSkip(test, reason)


def python_worker(start: Path, pattern: str, output: Path, verbose: bool) -> int:
    loader = unittest.TestLoader()
    # `x.tests` contiene un punto y no es un paquete importable. Descubrir desde
    # dentro reproduce exactamente `run-tests` y evita inventar nombres de módulo.
    os.chdir(start)
    suite = loader.discover(".", pattern=pattern)
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1, resultclass=TimedResult)
    # resultclass no permite pasar estado en el constructor; se inicializa al crear el resultado.
    original = runner._makeResult

    def make_result():
        result = original()
        result.timings = []
        return result

    runner._makeResult = make_result
    begun = time.perf_counter()
    result = runner.run(suite)
    payload = {
        "total_seconds": time.perf_counter() - begun,
        "count": result.testsRun,
        "failures": len(result.failures) + len(result.errors),
        "tests": sorted(result.timings, key=lambda x: x["seconds"], reverse=True),
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


def run(command: list[str], cwd: Path, quiet: bool = False) -> tuple[int, float]:
    print("$ " + " ".join(command), flush=True)
    begun = time.perf_counter()
    completed = subprocess.run(command, cwd=str(cwd),
                               stdout=subprocess.DEVNULL if quiet else None,
                               stderr=subprocess.STDOUT if quiet else None)
    return completed.returncode, time.perf_counter() - begun


def python_suite(python: str, temp: Path, verbose: bool, quiet: bool) -> dict:
    ignored = {".git", ".venv", "_build", "reports", "y.lcc"}
    directories = sorted({path.parent for path in ROOT.rglob("test_*.py")
                          if not ignored.intersection(path.relative_to(ROOT).parts)
                          and path.parent != ROOT / "tools"})
    tests = []
    groups = []
    total = 0.0
    exit_code = 0
    for index, directory in enumerate(directories):
        output = temp / f"python-{index}.json"
        command = [python, str(Path(__file__).resolve()), "--python-worker", str(directory),
                   "--worker-output", str(output)]
        if verbose:
            command.append("--verbose")
        code, wall = run(command, ROOT, quiet)
        data = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        relative = directory.relative_to(ROOT).as_posix()
        for item in data.get("tests", []):
            tests.append({**item, "name": f"{relative}/{item['name']}"})
        groups.append({"name": relative, "seconds": data.get("total_seconds", wall),
                       "count": data.get("count", 0), "exit_code": code})
        total += data.get("total_seconds", wall)
        exit_code = exit_code or code
    return {"name": "Python (todas las carpetas)", "kind": "python",
            "total_seconds": total, "wall_seconds": total, "exit_code": exit_code,
            "groups": sorted(groups, key=lambda x: x["seconds"], reverse=True),
            "count": len(tests),
            "tests": sorted(tests, key=lambda x: x["seconds"], reverse=True)}


def rtl_suite(python: str, prototype: str, full: bool, quiet: bool) -> dict:
    directory = resolve_prototype(prototype, root=ROOT)
    selected = testbenches(directory)
    slow = {p.name for p in slow_testbenches(directory)}
    if not full:
        selected = [p for p in selected if p.name not in slow]
    setup = []
    begun = time.perf_counter()
    code = stage_programs.stage(directory)
    fixture = fixtures_step(directory)
    if code == 0 and fixture:
        fixture_code, seconds = run(fixture, directory, quiet)
        setup.append({"name": "fixtures", "seconds": seconds, "exit_code": fixture_code})
        code = fixture_code
    apio = find_apio_binary(ROOT)
    benches = []
    if code == 0:
        for bench in selected:
            bench_code, seconds = run([apio, "test", "-p", str(directory), bench.name], directory, quiet)
            benches.append({"name": bench.name, "seconds": seconds, "exit_code": bench_code})
            code = code or bench_code
    return {"name": f"RTL ({directory.name})", "kind": "rtl",
            "total_seconds": time.perf_counter() - begun, "exit_code": code,
            "omitted_slow": sorted(slow) if not full else [], "setup": setup,
            "tests": sorted(benches, key=lambda x: x["seconds"], reverse=True)}


def x_suite(python: str, backend: str, temp: Path, prototype: str | None,
            cases: list[str], jobs: int, quiet: bool,
            skip_slow: bool = False, upload: bool = False,
            port: str | None = None) -> dict:
    output = temp / f"{backend}.json"
    command = [python, str(ROOT / "x.tests" / "run_tests.py"), "--backend", backend,
               "--jobs", str(jobs), "--timings-json", str(output)]
    if prototype:
        command += ["--prototype", prototype, "--yes" if upload else "--no-upload"]
    if port:
        command += ["--port", port]
    if skip_slow:
        command.append("--skip-slow")
    command += cases
    code, wall = run(command, ROOT / "x.tests", quiet)
    data = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    executions = data.pop("executions", [])
    return {"name": f"x.tests [{backend}]" + (f" ({prototype})" if prototype else ""),
            "kind": "x.tests", "total_seconds": data.get("total_seconds", wall),
            "wall_seconds": wall, "exit_code": code, "tests": [
                {"name": f'{item["case"]} [{item["backend"]}]', "seconds": item["seconds"]}
                for item in executions], "slow_cases_omitted": skip_slow, **data}


def duration(value: float) -> str:
    if value < 1:
        return f"{value * 1000:.1f} ms"
    if value < 60:
        return f"{value:.2f} s"
    return f"{int(value // 60)}m {value % 60:.1f}s"


def markdown(suites: list[dict], started: str, command: str) -> str:
    lines = ["# Tiempos de tests", "", f"Generado: {started}", "", f"Comando: `{command}`", "",
             "Los tiempos son de pared. En `x.tests`, `--jobs > 1` solapa casos: la suma de filas no coincide con el total.", "",
             "## Resumen", "", "| Suite | Total | Estado |", "|---|---:|---|"]
    for suite in suites:
        lines.append(f'| {suite["name"]} | {duration(suite.get("total_seconds", 0))} | '
                     f'{"OK" if suite.get("exit_code", 1) == 0 else "FALLO"} |')
    for suite in suites:
        lines += ["", f'## {suite["name"]}', "", f'Total: **{duration(suite.get("total_seconds", 0))}**.', "",
                  "| Test | Tiempo | Estado |", "|---|---:|---|"]
        for item in sorted(suite.get("tests", []), key=lambda x: x["seconds"], reverse=True):
            state = item.get("state", "OK" if item.get("exit_code", 0) == 0 else "FALLO")
            lines.append(f'| `{item["name"]}` | {duration(item["seconds"])} | {state} |')
        if suite.get("omitted_slow"):
            lines += ["", "Omitidos por `TEST-LENTO` (usa `--full`): " +
                      ", ".join(f'`{x}`' for x in suite["omitted_slow"]) + "."]
        if suite.get("slow_cases_omitted"):
            lines += ["", "Se omitieron los casos marcados con `slow` en su `test.json`."]
        if suite.get("groups"):
            lines += ["", "### Totales por carpeta", "", "| Carpeta | Tests | Tiempo | Estado |",
                      "|---|---:|---:|---|"]
            for group in suite["groups"]:
                lines.append(f'| `{group["name"]}` | {group["count"]} | '
                             f'{duration(group["seconds"])} | '
                             f'{"OK" if group["exit_code"] == 0 else "FALLO"} |')
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", action="append",
                        help="prototipo para bancos RTL; repetible (CPU y GPU más nuevas si se omite)")
    parser.add_argument("--cpu-prototype", help="añade x.tests en una placa CPU (sin cargar bitstream)")
    parser.add_argument("--gpu-prototype", help="añade x.tests en una placa GPU (sin cargar bitstream)")
    parser.add_argument("--skip-hardware", action="store_true",
                        help="no detecta ni modifica la placa")
    parser.add_argument("--cases", action="append", default=[], metavar="RUTA",
                        help="limita los casos x.tests; se puede repetir")
    parser.add_argument("--jobs", type=int, default=1,
                        help="procesos para x.tests (1 da tiempos y total comparables)")
    parser.add_argument("--full", action="store_true", help="incluye bancos RTL TEST-LENTO")
    parser.add_argument("--full-x-tests", action="store_true",
                        help="incluye en los simuladores GPU los casos marcados slow")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-rtl", action="store_true")
    parser.add_argument("--skip-x-tests", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="oculta la salida de cada subproceso")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "test-timings.md")
    parser.add_argument("--json", type=Path, help="guarda además los datos sin formato")
    parser.add_argument("--python-worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.python_worker:
        return python_worker(args.python_worker, "test_*.py", args.worker_output, args.verbose)
    if args.jobs < 1:
        parser.error("--jobs debe ser al menos 1")
    if args.skip_hardware and (args.cpu_prototype or args.gpu_prototype):
        parser.error("--skip-hardware no se combina con --cpu-prototype/--gpu-prototype")
    python = str(ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(python).exists():
        python = sys.executable
    suites = []
    started = time.strftime("%Y-%m-%d %H:%M:%S %z")
    hardware_port = None
    automatic_hardware = (not args.skip_hardware and not args.skip_x_tests
                          and not (args.cpu_prototype or args.gpu_prototype))
    if automatic_hardware:
        hardware_port = detected_board_port()
        if hardware_port is None:
            print("No se detectó ninguna placa FTDI; se omiten las medidas hardware.")
        else:
            args.cpu_prototype = newest_board_prototype("cpu")
            args.gpu_prototype = newest_board_prototype("gpu")
            print(f"Placa detectada en {hardware_port}; se medirán CPU {args.cpu_prototype} "
                  f"y GPU {args.gpu_prototype}, cargando sus bitstreams.")
    try:
        with tempfile.TemporaryDirectory(prefix="mini-gpu-test-timings-") as folder:
            temp = Path(folder)
            if not args.skip_python:
                suites.append(python_suite(python, temp, args.verbose, args.quiet))
            if not args.skip_rtl:
                rtl_prototypes = args.prototype or [
                    newest_board_prototype("cpu"),
                    newest_board_prototype("gpu"),
                ]
                for prototype in rtl_prototypes:
                    suites.append(rtl_suite(python, prototype, args.full, args.quiet))
            if not args.skip_x_tests:
                for backend in ("cpusim", "gpusim", "gpusim-cycle"):
                    skip_slow = (not args.full_x_tests
                                 and backend in ("gpusim", "gpusim-cycle"))
                    suites.append(x_suite(python, backend, temp, None, args.cases,
                                          args.jobs, args.quiet, skip_slow))
                if args.cpu_prototype:
                    suites.append(x_suite(python, "cpu-fpga", temp, args.cpu_prototype,
                                          args.cases, 1, args.quiet,
                                          upload=automatic_hardware, port=hardware_port))
                if args.gpu_prototype:
                    suites.append(x_suite(python, "gpu-fpga", temp, args.gpu_prototype,
                                          args.cases, 1, args.quiet,
                                          upload=automatic_hardware, port=hardware_port))
    except (PrototypeResolutionError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown(suites, started, " ".join(sys.argv)), encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"generated": started, "suites": suites}, indent=2) + "\n", encoding="utf-8")
    print(f"Informe: {args.output}")
    return 1 if any(s.get("exit_code", 1) != 0 for s in suites) else 0


if __name__ == "__main__":
    raise SystemExit(main())
