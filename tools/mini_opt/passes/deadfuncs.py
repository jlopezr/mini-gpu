"""Borra las funciones que nadie nombra: ni la propia unidad ni el resto del programa.

Solo con `--whole-program`, que promete que los `--extern-refs` son TODO lo demas que se ensambla con la
unidad (el arranque, el runtime, las otras unidades). Sin esa promesa no se borra nada: que un fichero ajeno no
nombre una funcion no demuestra que no la use otro que no se ha pasado (con `--extern-refs` solo, lo peor que
pasa es que `licm` se queda corto; aqui seria borrar codigo vivo).

Como un enlazador: las raices son lo que se nombra fuera de las funciones de la unidad (en un fichero ajeno,
como `main` en el arranque, o en los datos, como `.word f` de una tabla) y los kernels (`__kernel_*`): un kernel es
un punto de entrada que se lanza por su direccion, y quien lo lanza no tiene por que estar en el programa (los
arneses de `32.cpu-gpu-func-sim/compare` compilan solo kernels y los lanzan desde Python). Esta viva toda funcion que se alcanza
desde ellas siguiendo lo que nombra cada cuerpo (`JAL`, `LI` de un puntero a funcion). Las demas se borran, aunque
se llamen entre ellas (recursion, `ping`/`pong`). No cuentan las declaraciones (`.globl f`, `.global f`,
`.extern f`) ni los comentarios.

Las referencias ajenas salen de los `.s` de las otras unidades tal como llegan a `mini-opt`, sin optimizar, asi
que una funcion que solo llamaba otra unidad desde codigo que luego se borra se conserva: sobra codigo, pero
nunca se borra algo vivo.
"""
from __future__ import annotations

from ..model import SYMBOL_RE, Function, Line, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX

# Los pone la linea de ordenes (`--whole-program`, `--extern-refs`).
WHOLE_PROGRAM = False
EXTERNAL: frozenset[str] = frozenset()

DECLARATIONS = (".globl", ".global", ".extern")
SECTION_WORDS = (".text", ".code", ".data", ".bss", ".rodata", ".rdata")


def external_names(text: str) -> set[str]:
    """Los nombres que usa un fichero ensamblado aparte, sin sus comentarios."""
    return {name for raw in text.splitlines() for name in SYMBOL_RE.findall(raw.split(";", 1)[0])}


def directive_word(line: Line) -> str:
    return line.text.split(None, 1)[0].lower() if line.kind == "directive" else ""


def names_used(line: Line) -> list[str]:
    """Lo que una linea nombra como uso: operandos de instrucciones y de directivas que no son declaraciones."""
    if line.kind == "instr":
        return [name for arg in line.args for name in SYMBOL_RE.findall(arg)]
    if line.kind == "directive" and directive_word(line) not in DECLARATIONS:
        parts = line.text.split(None, 1)
        return SYMBOL_RE.findall(parts[1]) if len(parts) > 1 else []
    return []


def declares_any(line: Line, names: set[str]) -> bool:
    """`.globl f` (o `.global`, `.extern`) de alguna de `names`."""
    if directive_word(line) not in DECLARATIONS:
        return False
    parts = line.text.split(None, 1)
    return len(parts) > 1 and any(name in names for name in SYMBOL_RE.findall(parts[1]))


@register_pass("deadfuncs", "con --whole-program: borra las funciones que nadie nombra (ni la unidad ni el resto)")
def pass_deadfuncs(unit: Unit, stats: dict) -> None:
    if not WHOLE_PROGRAM:
        return
    calls: dict[str, set[str]] = {}         # funcion -> lo que nombra su cuerpo
    roots: set[str] = set(EXTERNAL)         # lo que se nombra fuera de las funciones de la unidad
    for chunk in unit.chunks:
        if isinstance(chunk, Function):
            calls[chunk.name] = {name for line in chunk.header + chunk.body for name in names_used(line)}
        else:
            roots.update(names_used(chunk))
    live: set[str] = set()
    pending = [name for name in calls if name in roots or name.startswith(KERNEL_PREFIX)]
    while pending:
        name = pending.pop()
        if name in live:
            continue
        live.add(name)
        pending.extend(callee for callee in calls[name] if callee in calls)
    dead = {name for name in calls if name not in live}
    if not dead:
        return
    stats["deadfuncs.removed"] = stats.get("deadfuncs.removed", 0) + len(dead)
    chunks = []
    for chunk in unit.chunks:
        if isinstance(chunk, Function) and chunk.name in dead:
            # Se quedan los cambios de seccion de la cabecera: lo que viene detras puede contar con ellos.
            chunks += [line for line in chunk.header if directive_word(line) in SECTION_WORDS]
        elif isinstance(chunk, Function):
            chunk.header = [line for line in chunk.header if not declares_any(line, dead)]
            chunk.body = [line for line in chunk.body if not declares_any(line, dead)]
            chunks.append(chunk)
        elif not declares_any(chunk, dead):     # su `.globl`, este donde este (lcc lo puede dejar en `.data`)
            chunks.append(chunk)
    unit.chunks = chunks
