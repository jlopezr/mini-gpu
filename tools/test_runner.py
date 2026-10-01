#!/usr/bin/env python3
"""Ejecuta la suite de un prototipo: fixtures (si las tiene) + tests Python
(si los tiene) + regresión RTL de apio (si tiene apio.ini) + lint opcional.

Genérico: no depende de qué prototipo es. Cada paso se salta con claridad si
no aplica a ese prototipo en concreto, en vez de fingir que existe."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import stage_programs
from tools.prototype import PrototypeResolutionError, find_apio_binary, find_repo_root, resolve_prototype


SLOW_MARKER = "TEST-LENTO"


def slow_testbenches(prototype_dir: Path) -> list[Path]:
    """Bancos marcados como lentos, para dejarlos fuera de la pasada normal.

    La marca vive DENTRO del banco (un comentario con TEST-LENTO y el motivo) y
    no en una lista aparte a proposito: una lista se desincroniza en cuanto
    alguien renombra o borra un banco, y nadie se entera hasta que el filtro
    deja de filtrar en silencio.
    """
    found = []
    for path in sorted(prototype_dir.glob("*_tb.v")) + sorted(prototype_dir.glob("*_tb.sv")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if SLOW_MARKER in text:
            found.append(path)
    return found


TEMP_PREFIX = "_tmp_test_"
# Lo que no se copia a las carpetas de trabajo: historial pesado y estado de build.
NO_COPIAR = {"reports", "_build", "__pycache__", ".git"}


def testbenches(prototype_dir: Path) -> list[Path]:
    return sorted(prototype_dir.glob("*_tb.v")) + sorted(prototype_dir.glob("*_tb.sv"))


def _copy_worktree(prototype_dir: Path, dest: Path, keep: set[str]) -> dict[str, int]:
    """Copia el prototipo a `dest` con SOLO los bancos de `keep`.

    Devuelve el mtime (ns) de cada fichero de la raiz, para saber luego cuales
    ha escrito un banco. `reports/` y `_build/` no se copian: pesan gigas y
    apio no los necesita para simular.
    """
    dest.mkdir()
    mtimes = {}
    todos = {p.name for p in testbenches(prototype_dir)}
    for item in prototype_dir.iterdir():
        if item.name in NO_COPIAR:
            continue
        if item.is_dir():
            shutil.copytree(item, dest / item.name)
        elif item.name in todos and item.name not in keep:
            continue
        else:
            shutil.copy2(item, dest / item.name)
            mtimes[item.name] = (dest / item.name).stat().st_mtime_ns
    return mtimes


def _copy_back(dest: Path, prototype_dir: Path, mtimes: dict[str, int]) -> None:
    """Devuelve los ficheros de la raiz que un banco ha creado o modificado.

    Algunos bancos escriben en su directorio de trabajo (`frame_full.hex/.bin`,
    que luego se miran a mano). Con las copias aisladas esos ficheros se
    perderian; asi el resultado en el directorio del prototipo es el de siempre.
    """
    for item in dest.iterdir():
        if not item.is_file() or item.name in NO_COPIAR:
            continue
        if mtimes.get(item.name) != item.stat().st_mtime_ns:
            shutil.copy2(item, prototype_dir / item.name)


def run_rtl_parallel(apio: str, prototype_dir: Path, benches: list[Path], jobs: int) -> list[str]:
    """`apio test` sobre `jobs` grupos de bancos a la vez. Devuelve los fallos.

    Cada grupo corre en su propia copia (hermana de la carpeta, para que las
    rutas relativas `..\\x.tests\\...` sigan valiendo): apio/scons guardan estado
    en el proyecto, y dos `apio test` sobre la misma carpeta se pisarian. Es UNA
    invocacion de apio por grupo, no una por banco, para no pagar el arranque de
    scons en cada uno.

    El reparto es por turnos, sin mas: en la 30 un banco de 115 s pesa mas que los
    otros treinta juntos, y con esa forma cualquier reparto acaba en lo que tarda
    el grupo que lo lleva.
    """
    groups = [benches[i::jobs] for i in range(jobs) if benches[i::jobs]]
    parent = prototype_dir.parent
    dirs = [parent / f"{TEMP_PREFIX}{k}_{prototype_dir.name}" for k in range(len(groups))]
    print(f"== regresión RTL (apio test), {len(benches)} bancos en {len(groups)} grupos en paralelo",
          flush=True)
    results = []
    try:
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)      # sobrante de una ejecucion interrumpida
        state = [_copy_worktree(prototype_dir, d, {b.name for b in g}) for d, g in zip(dirs, groups)]

        def run(index):
            started = time.monotonic()
            done = subprocess.run([apio, "test", "-p", str(dirs[index])], cwd=str(dirs[index]),
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            return done, time.monotonic() - started

        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            results = list(pool.map(run, range(len(groups))))
        for d, mtimes in zip(dirs, state):
            _copy_back(d, prototype_dir, mtimes)
    finally:
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)

    failures = []
    for k, (group, (done, seconds)) in enumerate(zip(groups, results), start=1):
        print(f"== grupo {k}/{len(groups)}: {len(group)} bancos, {seconds:.1f} s "
              f"({', '.join(p.name for p in group)})", flush=True)
        print(done.stdout, end="", flush=True)
        if done.stderr:
            print(done.stderr, end="", file=sys.stderr, flush=True)
        if done.returncode != 0:
            print(f"!! apio test (grupo {k}) falló (exit {done.returncode})", file=sys.stderr)
            failures.append(f"apio test (grupo {k})")
    return failures


def fixtures_step(prototype_dir: Path) -> list[str] | None:
    """Comando que deja `fixtures/` al día, o None si el prototipo no las usa."""
    from tools import make_rtl_fixtures

    if make_rtl_fixtures.consumes_fixtures(prototype_dir):
        return [sys.executable, str(ROOT / "tools" / "make_rtl_fixtures.py"),
                "--prototype", str(prototype_dir)]
    own = prototype_dir / "make_fixtures.py"
    return [sys.executable, str(own)] if own.exists() else None


def run_step(name: str, command: list[str], cwd: Path) -> int:
    print(f"== {name}", flush=True)
    print(f"$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=str(cwd))
    if completed.returncode != 0:
        print(f"!! {name} falló (exit {completed.returncode})", file=sys.stderr)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--prototype", required=True)
    parser.add_argument("--quick", action="store_true", help="solo fixtures + tests Python, sin apio test")
    parser.add_argument("--full", "--slow", dest="full", action="store_true",
                        help="incluye los bancos marcados TEST-LENTO (por defecto se omiten)")
    parser.add_argument("--lint", action="store_true", help="añade apio lint")
    parser.add_argument("--lint-only", action="store_true",
                        help="solo apio lint: sin fixtures, tests Python ni regresión RTL")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--jobs", type=int, default=2,
                        help="grupos de bancos RTL en paralelo, cada uno en su copia de la carpeta "
                             "(por defecto 2; 1 = una sola invocacion de apio, como antes)")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs tiene que ser al menos 1")
    if args.lint_only:
        args.lint = True

    root = find_repo_root(Path.cwd())
    try:
        prototype_dir = resolve_prototype(args.prototype, root=root)
    except PrototypeResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Using prototype: {prototype_dir.name}")

    ran_something = False
    failures: list[str] = []

    # Los bancos leen `examples/<x>.hex`; el fuente vive en x.tests. Sin esto, un
    # clon limpio no tiene con que correr `gpu_plasma_tb` y compania.
    if not args.lint_only and stage_programs.stage(prototype_dir) != 0:
        failures.append("programas")
        return _summarize(failures)

    # Los bancos diferenciales de GPU leen `fixtures/` (ignorada por git): se
    # regeneran con el generador compartido. `make_fixtures.py` propio queda como
    # alternativa para un prototipo que necesite el suyo.
    fixtures_command = fixtures_step(prototype_dir)
    if fixtures_command is not None and not args.lint_only:
        ran_something = True
        if run_step("fixtures", fixtures_command, prototype_dir) != 0:
            failures.append("fixtures")
            return _summarize(failures)

    if any(prototype_dir.glob("test_*.py")) and not args.lint_only:
        ran_something = True
        command = [sys.executable, "-m", "unittest", "discover", "-s", str(prototype_dir), "-p", "test_*.py"]
        if args.verbose:
            command.append("-v")
        if run_step("tests Python", command, prototype_dir) != 0:
            failures.append("tests Python")

    apio_ini = prototype_dir / "apio.ini"
    skipped_rtl_test = False
    if apio_ini.exists():
        apio = find_apio_binary(root)
        if args.quick or args.lint_only:
            skipped_rtl_test = True
        else:
            ran_something = True
            slow = slow_testbenches(prototype_dir)
            slow_names = {path.name for path in slow}
            rapidos = [path for path in testbenches(prototype_dir)
                       if args.full or path.name not in slow_names]
            if args.jobs > 1 and len(rapidos) > 1:
                if slow and not args.full:
                    print("   omitidos por lentos (usa --full para incluirlos): "
                          + ", ".join(sorted(slow_names)), flush=True)
                failures.extend(run_rtl_parallel(apio, prototype_dir, rapidos, args.jobs))
            elif not slow or args.full:
                # Sin bancos lentos (o con --full) se deja hacer a apio, que es
                # una sola invocacion y la salida de siempre.
                if run_step("regresión RTL (apio test)",
                            [apio, "test", "-p", str(prototype_dir)], prototype_dir) != 0:
                    failures.append("apio test")
            else:
                slow_names = {path.name for path in slow}
                todos = sorted(prototype_dir.glob("*_tb.v")) + sorted(prototype_dir.glob("*_tb.sv"))
                rapidos = [path for path in todos if path.name not in slow_names]
                print(f"== regresión RTL (apio test), {len(rapidos)} bancos", flush=True)
                print("   omitidos por lentos (usa --full para incluirlos): "
                      + ", ".join(sorted(slow_names)), flush=True)
                for path in rapidos:
                    if run_step(f"apio test {path.name}",
                                [apio, "test", "-p", str(prototype_dir), path.name],
                                prototype_dir) != 0:
                        failures.append(f"apio test {path.name}")
                        break
        if args.lint:
            ran_something = True
            if run_step("lint (apio lint)", [apio, "lint", "-p", str(prototype_dir)], prototype_dir) != 0:
                failures.append("apio lint")
    elif args.lint:
        print(f"aviso: {prototype_dir.name} no tiene apio.ini; --lint no aplica.", file=sys.stderr)

    if not ran_something:
        if skipped_rtl_test:
            print(f"aviso: {prototype_dir.name} no tiene test_*.py; la regresión RTL se omitió por --quick.", file=sys.stderr)
        else:
            print(f"aviso: {prototype_dir.name} no tiene nada que probar (ni test_*.py, ni apio.ini).", file=sys.stderr)

    return _summarize(failures)


def _summarize(failures: list[str]) -> int:
    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
