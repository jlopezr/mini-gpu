"""Comprueba qué limitaciones de Codon siguen vigentes con el compilador instalado.

Cada `lNN_*.py` es un programa mínimo, válido en Python, que imprime «OK». Con
la versión con la que se escribió (0.20.5) ninguno compila o funciona en Codon:
si alguno pasa a imprimir «OK», esa limitación se ha resuelto y su docstring
dice qué rodeo del simulador se puede deshacer. Detalles en `LIMITACIONES.md`.

    python3 tools/codon/limitations/check.py [--codon RUTA]

Sale con 0 si todas siguen como se documentaron y con 1 si alguna ha cambiado
(resuelta, o rota en Python), para que no pase desapercibido al actualizar.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))


def cases() -> list[Path]:
    return sorted(HERE.glob("l[0-9][0-9]_*.py"))


def python_result(path: Path) -> str:
    """La salida en Python. `dataclass` llega ya definido: l04 no lo importa
    para que en Codon falle por `frozen` y no por el import (eso es l03)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        runpy.run_path(str(path), init_globals={"dataclass": dataclasses.dataclass},
                       run_name="__main__")
    return out.getvalue().strip()


def codon_result(codon: str, path: Path) -> tuple[bool, str]:
    """(imprime «OK», primera línea de error o de salida)."""
    proc = subprocess.run([codon, "run", str(path)], capture_output=True, text=True,
                          cwd=path.parent, timeout=300)
    text = (proc.stdout + proc.stderr).strip()
    first = next((line for line in text.splitlines() if line.strip()), "")
    for code in ("\x1b[1m", "\x1b[0m", "\x1b[1;31m", "\x1b[32m"):
        first = first.replace(code, "")
    return proc.returncode == 0 and proc.stdout.strip() == "OK", first.replace(str(path.parent) + "/", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--codon", help="compilador (por defecto, el del backend)")
    args = parser.parse_args(argv)
    if args.codon:
        codon = args.codon
    else:
        from tools.codon_backend import compiler
        codon = compiler()
    version = subprocess.check_output([codon, "--version"], text=True).strip()
    print(f"Codon {version}")
    changed = 0
    for path in cases():
        if path.name.startswith("l07") and sys.version_info < (3, 14):
            in_python = "OK"    # sin anotaciones diferidas no se puede probar en Python
        else:
            try:
                in_python = python_result(path)
            except Exception as exc:  # noqa: BLE001 - se informa y se cuenta
                in_python = f"{type(exc).__name__}: {exc}"
        works, detail = codon_result(codon, path)
        if in_python != "OK":
            changed += 1
            print(f"  ROTA EN PYTHON  {path.name}: {in_python}")
        elif works:
            changed += 1
            print(f"  RESUELTA        {path.name}: se puede deshacer su rodeo (ver docstring)")
        else:
            print(f"  sigue           {path.name}: {detail[:110]}")
    if changed:
        print(f"{changed} limitación(es) han cambiado: revisa LIMITACIONES.md")
    return 1 if changed else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.exit(main())
