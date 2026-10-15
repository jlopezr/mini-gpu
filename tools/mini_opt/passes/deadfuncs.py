"""Borra las funciones que nadie alcanza, en un programa entero (`--whole-program`).

Solo tiene sentido cuando el `.s` es todo el programa: en un `.s` suelto cualquier funcion publica puede
llamarla otra unidad, asi que sin la bandera el pase no hace nada. Se queda con lo que alcanza una raiz:

  - `main` y `_start`;
  - lo que nombran los ficheros ensamblados aparte (`--extern-refs`: el arranque, el runtime...);
  - los kernels (`KERNEL_PREFIX`): los lanza el anfitrion por su etiqueta, y no los llama ningun codigo;
  - lo que un dato mencione (`.word f`: una tabla de punteros a funcion).

y todo lo que esas funciones llamen o cuya direccion tomen, de forma transitiva. Los datos no se tocan: los
anfitriones (tests, depuradores) leen globales por su etiqueta.

Va el primero del pipeline: el codigo muerto que escribe una global o toma una direccion hace que `licm`
descarte simbolos como "alcanzables por un puntero"."""
from __future__ import annotations

from ..model import SYMBOL_RE, Function, Line, Unit
from ..registry import register_pass
from . import licm
from .kernels import KERNEL_PREFIX

WHOLE_PROGRAM = False
ENTRY_POINTS = frozenset({"main", "_start"})

# Directivas que nombran un simbolo sin usarlo: no mantienen viva una funcion.
DECLARATIONS = frozenset({".globl", ".global", ".extern", ".comm", ".equ", ".set", ".align", ".text", ".code",
                          ".data", ".bss", ".rodata", ".rdata", ".once", ".define"})


def calls_of(function: Function, functions: dict[str, Function]) -> set[str]:
    return {name for line in function.body if line.kind == "instr"
            for arg in line.args for name in SYMBOL_RE.findall(arg) if name in functions}


def named_by_data(unit: Unit, functions: dict[str, Function]) -> set[str]:
    names: set[str] = set()
    for chunk in unit.chunks:
        if isinstance(chunk, Line) and chunk.kind == "directive":
            word, _, rest = chunk.text.partition(" ")
            if word.lower() not in DECLARATIONS:
                names.update(name for name in SYMBOL_RE.findall(rest) if name in functions)
    return names


@register_pass("deadfuncs", "con --whole-program, borra las funciones que no alcanza main, el arranque ni un kernel")
def pass_deadfuncs(unit: Unit, stats: dict) -> None:
    if not WHOLE_PROGRAM:
        return
    functions = {function.name: function for function in unit.functions()}
    live = {name for name in functions
            if name in ENTRY_POINTS or name in licm.EXTERNAL or name.startswith(KERNEL_PREFIX)}
    live |= named_by_data(unit, functions)
    pending = list(live)
    while pending:
        for name in calls_of(functions[pending.pop()], functions):
            if name not in live:
                live.add(name)
                pending.append(name)
    dead = [name for name in functions if name not in live]
    if not dead:
        return
    stats["deadfuncs.removed"] = stats.get("deadfuncs.removed", 0) + len(dead)
    unit.chunks = [chunk for chunk in unit.chunks
                   if not (isinstance(chunk, Function) and chunk.name not in live)]
