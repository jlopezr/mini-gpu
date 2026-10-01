#!/usr/bin/env python3
"""Ensambla en `<prototipo>/examples/` los programas que sus bancos Verilog leen.

Los fuentes `.asm` viven una sola vez, bajo `x.tests/cases-cpu*/`. Los testbenches
`.v`, en cambio, hacen `$readmemh("examples/plasma.hex")` con una ruta relativa
a su carpeta; en vez de tocar cada banco, este paso deja ahí el `.bin`/`.hex`
que piden. No hay lista que mantener: se leen las referencias `examples/<x>.bin`
o `.hex` de los `.v` del prototipo y se busca `<x>.asm` bajo `x.tests`.

Lo que se genera no se versiona (`examples/*.bin` y `*.hex` en el `.gitignore`
del prototipo).

    stage_programs.py --prototype 22
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "1.isa"), str(ROOT)]

from mini_asm import assemble_bytes, write_hex  # noqa: E402

REFERENCIA = re.compile(r"""examples/([A-Za-z0-9_\-]+)\.(bin|hex)\b""")
FUENTES = ROOT / "x.tests"
INCLUDES = (FUENTES / "inc",)


def buscar_fuente(nombre: str) -> Path | None:
    """`plasma` -> `x.tests/.../plasma.asm`. Dos coincidencias es un error.

    Se busca por nombre solo lo que un banco pide, no se indexa todo: los casos
    se llaman casi todos `program.asm`, y ahi el nombre no identifica nada.
    Las variantes antiguas (`simt.legacy-12-14-17.asm`) llevan un punto en el
    nombre y no se confunden con la actual."""
    coincidencias = [ruta for carpeta in ("cases-cpu", "cases-gpu", "cases-shared")
                     for ruta in sorted((FUENTES / carpeta).rglob(f"{nombre}.asm"))]
    if len(coincidencias) > 1:
        raise SystemExit(f"error: {nombre}.asm esta mas de una vez: "
                         + ", ".join(str(c.relative_to(ROOT)) for c in coincidencias))
    return coincidencias[0] if coincidencias else None


def pedidos(prototipo: Path) -> dict[str, set[str]]:
    """Programas que los `.v` del prototipo leen de `examples/`, con sus extensiones."""
    resultado: dict[str, set[str]] = {}
    for banco in prototipo.glob("*.v"):
        for nombre, extension in REFERENCIA.findall(banco.read_text(encoding="utf-8", errors="replace")):
            resultado.setdefault(nombre, set()).add(extension)
    return resultado


def stage(prototipo: Path) -> int:
    quiero = pedidos(prototipo)
    if not quiero:
        return 0
    destino = prototipo / "examples"
    destino.mkdir(exist_ok=True)
    faltan = []
    for nombre, extensiones in sorted(quiero.items()):
        fuente = buscar_fuente(nombre)
        if fuente is None:
            faltan.append(nombre)
            continue
        imagen = assemble_bytes(fuente.read_text(encoding="utf-8"), fuente.parent,
                                str(fuente), INCLUDES)
        (destino / f"{nombre}.bin").write_bytes(imagen)
        write_hex(imagen, destino / f"{nombre}.hex")
        print(f"  {fuente.relative_to(ROOT)} -> {destino.relative_to(ROOT)}/{nombre}.bin/.hex")
    if faltan:
        print(f"error: sin fuente en x.tests: {', '.join(faltan)}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prototype", required=True)
    args = parser.parse_args()
    from tools.prototype import resolve_prototype
    return stage(resolve_prototype(args.prototype, root=ROOT))


if __name__ == "__main__":
    sys.exit(main())
