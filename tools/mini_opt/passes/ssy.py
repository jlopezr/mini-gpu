"""SSY automatico: donde reconvergen los caminos de un salto divergente

Un salto condicional cuyas lanes toman caminos distintos necesita una region
abierta con `SSY join` (isa.md): sin ella el SM para con ERROR_SIMT. `join` es el
postdominador inmediato del salto, el primer punto por el que pasan todos los
caminos. En un bucle cuyas lanes salen en vueltas distintas, la region se abre
una vez antes del bucle (en el preheader), con el punto de salida como join; asi
valen tanto el salto de vuelta como cualquier `break`.

Solo hace falta para los saltos que PUEDEN divergir. Un valor varia entre lanes si
viene de GETTID o GETLANE y se propaga por la aritmetica y las cargas; lo que se
define bajo un salto divergente tambien varia. La pila es de cada lane, pero lo que
se guarda en un hueco y se vuelve a leer no varia si no variaba al guardarlo: se
siguen los huecos (por su posicion respecto al origen de la pila de la lane, como
`stackslots`) mientras ninguna direccion de la pila se escape a un registro; si se
escapa, toda carga de la pila varia. Importa con las funciones expandidas
(`kernelcalls`): lcc les pasa por la pila los parametros a partir del quinto y
guarda en ella los que derrama, y sin esto cada `if` sobre ellos abriria una region.
Con `SSY_ALL` se trata todo salto condicional como divergente.

Un `SSY` que cae siempre despues de otro con el mismo destino sobra: la region ya esta
abierta, y dentro de ella pueden divergir varios saltos (un `if / else if`).

La GPU guarda las regiones abiertas en una pila de `MAX_REGIONS` niveles; con una mas, para con
ERROR_SIMT. Al final se comprueba que ningun `SSY` puede abrir su region con la pila llena: su
profundidad es 1 mas las regiones de los otros `SSY` que lo contienen (lo que se alcanza desde
cada uno antes de su destino). Es una cota por arriba, y pasarse es un error al compilar."""
from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import NamedTuple

from ..flow import (
    Block,
    build_cfg,
    dominators,
    immediate_postdominator,
    natural_loops,
    postdominators,
    predecessors,
)
from ..isa import BRANCHES, LOADS, STACK, STORES, defs_uses, instr, reg_of
from ..model import Function, Line, OptError, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX
from .stackslots import WIDTH, stack_positions

SSY_ALL = False

# La pila de regiones SIMT: SIMT_REGION_DEPTH de gpu_sm.v (36, 37) y MAX_SIMT_REGIONS de los simuladores 11 y 25.
MAX_REGIONS = 8

VARYING_SOURCES = {"GETTID", "GETLANE"}

UNIFORM_SOURCES = {"MOVI", "MOVHI", "LI", "GETWARP", "GETLWARP", "GETARG"}


# ---------------------------------------------------------------------------
# Que saltos pueden divergir
# ---------------------------------------------------------------------------

# Lo que varia entre lanes: registros (int) y bytes de la pila (("pila", posicion)).
Varying = set

def stack_bytes(blocks: list[Block]) -> dict[int, list[tuple[str, int]]] | None:
    """Los bytes de la pila que toca cada `LOAD`/`STORE` con base R30 (`id(linea) -> claves`), o None si la
    pila se usa de otra forma (`stack_positions`)."""
    positions = stack_positions(blocks)
    if positions is None:
        return None
    lines = {id(line): line for block in blocks for line in block.lines}
    return {key: [("pila", start + k) for k in range(WIDTH[lines[key].op])] for key, start in positions.items()}


def step_variance(var: Varying, line: Line, under_divergence: bool,
                  stack: dict[int, list[tuple[str, int]]] | None = None) -> Varying:
    """Lo que varia entre lanes tras `line`. Lo que se define bajo un salto divergente varia."""
    keys = stack.get(id(line)) if stack is not None else None
    if line.op in STORES:
        if keys is None:
            return var
        value = reg_of(line.args[0])
        return var | set(keys) if under_divergence or value in var else var - set(keys)
    defs, uses = defs_uses(line)
    if not defs:
        return var
    if line.op in VARYING_SOURCES or under_divergence:
        varying = True
    elif line.op in UNIFORM_SOURCES:
        varying = False
    elif line.op in LOADS:
        base = reg_of(line.args[1])
        if keys is not None:
            varying = any(k in var for k in keys)                       # lo que se guardo en el hueco
        else:
            varying = base == STACK or (base is not None and base in var)  # direccion distinta = dato distinto
    else:
        varying = bool(uses & var)
    return (var | defs) if varying else (var - defs)


def varying_on_entry(blocks: list[Block], tainted: set[int],
                     stack: dict[int, list[tuple[str, int]]] | None = None) -> list[Varying]:
    """Lo que varia entre lanes a la entrada de cada bloque (punto fijo)."""
    var_in: list[Varying] = [set() for _ in blocks]
    changed = True
    while changed:
        changed = False
        for block in blocks:
            var = set(var_in[block.index])
            for line in block.lines:
                if line.kind == "instr":
                    var = step_variance(var, line, block.index in tainted, stack)
            for s in block.succ:
                if not var <= var_in[s]:
                    var_in[s] |= var
                    changed = True
    return var_in


def blocks_under(blocks: list[Block], pdom: list[set[int]], branches: set[int]) -> set[int]:
    """Bloques que se ejecutan bajo alguno de esos saltos: de unas lanes y no de otras."""
    region: set[int] = set()
    for b in branches:
        join = immediate_postdominator(pdom, b)
        stack = list(blocks[b].succ)
        while stack:
            x = stack.pop()
            if x == join or x in region:
                continue
            region.add(x)
            stack.extend(blocks[x].succ)
    return region


def divergent_branches(blocks: list[Block], pdom: list[set[int]]) -> set[int]:
    """Indices de los bloques cuyo salto condicional puede divergir."""
    branch_of: dict[int, Line] = {}
    for block in blocks:
        last = block.last_instr()
        if last is not None and last.op in BRANCHES:
            branch_of[block.index] = last
    if SSY_ALL:
        return set(branch_of)
    stack = stack_bytes(blocks)
    tainted: set[int] = set()
    while True:
        var_in = varying_on_entry(blocks, tainted, stack)
        found: set[int] = set()
        for block in blocks:
            branch = branch_of.get(block.index)
            if branch is None:
                continue
            var = set(var_in[block.index])
            for line in block.lines[:-1]:
                if line.kind == "instr":
                    var = step_variance(var, line, block.index in tainted, stack)
            if any(r in var for r in map(reg_of, branch.args[:2]) if r is not None):
                found.add(block.index)
        region = blocks_under(blocks, pdom, found)
        if region <= tainted:
            return found
        tainted |= region


# ---------------------------------------------------------------------------
# Donde se pone cada SSY
# ---------------------------------------------------------------------------

class Edit(NamedTuple):
    """Un `SSY join` por poner en `block`, delante de la instruccion `position` (None = al final)."""
    block: Block
    position: int | None
    join: int


def common_postdominator(targets: list[int], pdom: list[set[int]], where: str) -> int:
    common = set.intersection(*(pdom[t] for t in targets))
    if not common:
        raise OptError(f"{where}: no encuentro donde reconvergen las salidas de un bucle")
    return max(common, key=lambda p: len(pdom[p]))


def loop_edits(blocks: list[Block], div: set[int], pdom: list[set[int]], where: str,
               name: str = "") -> tuple[list[Edit], set[int], list[Block]]:
    """Un SSY en el preheader de cada bucle cuyas salidas divergen. Devuelve (edits, saltos cubiertos, bloques
    nuevos). Si se entra al bucle desde un salto condicional, el SSY no puede ir delante del salto (abriria la
    region tambien por el otro camino): va en un trampolin nuevo, `pre: SSY join; BRA cabecera`, al que se
    redirige el salto. Los trampolines se anaden al final de la funcion (detras de su ultimo salto)."""
    preds = predecessors(blocks)
    succ = [list(block.succ) for block in blocks]       # los de antes de los trampolines (pdom es de estos)
    edits: list[Edit] = []
    handled: set[int] = set()
    trampolines: list[Block] = []
    for header, body in sorted(natural_loops(blocks, dominators(blocks)).items()):
        exits = [b for b in body if b in div and any(s not in body for s in succ[b])]
        if not exits:
            continue
        targets = sorted({s for b in exits for s in succ[b] if s not in body})
        join = targets[0] if len(targets) == 1 else common_postdominator(targets, pdom, where)
        handled |= {b for b in exits if immediate_postdominator(pdom, b) == join}
        if not any(b in handled for b in exits):
            continue
        for p in preds[header]:
            if p in body:
                continue
            term = blocks[p].last_instr()
            position = None
            if term is not None and term.op == "BRA":
                position = max(i for i, l in enumerate(blocks[p].lines) if l is term)
            elif term is not None and term.op in BRANCHES:
                labels = {l.name for l in blocks[header].lines if l.kind == "label"}
                if term.args[-1] in labels:                     # entra saltando: trampolin
                    if p + 1 == header:
                        raise OptError(f"{where}: un salto condicional entra dos veces en un bucle con "
                                       "divergencia; no se sabe donde abrir su region")
                    last = blocks[-1].last_instr()
                    if last is None or last.op not in ("BRA", "EXIT", "HALT", "JR"):
                        raise OptError(f"{where}: la funcion no acaba en un salto; no hay sitio para el "
                                       "trampolin de un bucle con divergencia")
                    label = f"__ssy_{name}_pre{len(trampolines) + 1}"
                    jump = Line("instr", "", op="BRA", args=[term.args[-1]])
                    trampoline = Block(len(blocks) + len(trampolines), [Line("label", "", name=label), jump],
                                       [header])
                    term.args[-1] = label
                    blocks[p].succ = [trampoline.index if s == header else s for s in blocks[p].succ]
                    trampolines.append(trampoline)
                    edits.append(Edit(trampoline, 1, join))
                    continue
                # cae en el bucle: el SSY va detras del salto, en el camino que entra
            elif term is not None and term.op in ("EXIT", "HALT", "JR"):
                raise OptError(f"{where}: la entrada a un bucle con divergencia sale de un salto "
                               "condicional; no se sabe donde abrir su region")
            edits.append(Edit(blocks[p], position, join))
    return edits, handled, trampolines


def branch_edits(blocks: list[Block], branches: set[int], pdom: list[set[int]], where: str) -> list[Edit]:
    """Un SSY delante de cada salto divergente que no es de un bucle, con su postdominador como destino."""
    edits = []
    for b in sorted(branches):
        join = immediate_postdominator(pdom, b)
        if join >= len(blocks):
            raise OptError(f"{where}: un salto divergente no reconverge antes de salir del kernel")
        edits.append(Edit(blocks[b], len(blocks[b].lines) - 1, join))
    return edits


def reach(starts: set[int], avoid: set[int], edges: list[list[int]]) -> set[int]:
    """Bloques alcanzables desde `starts` sin pasar por `avoid`."""
    seen: set[int] = set()
    stack = [s for s in starts if s not in avoid]
    while stack:
        x = stack.pop()
        if x in seen or x in avoid:
            continue
        seen.add(x)
        stack.extend(edges[x])
    return seen


def is_redundant(second: Edit, first: Edit, edits: list[Edit], blocks: list[Block]) -> bool:
    """`second` sobra si todo camino hasta su bloque pasa por `first` (mismo destino) y por el camino no se
    abre otra region con otro destino, que seria la mas interna."""
    if first is second or first.join != second.join or first.block.index == second.block.index:
        return False
    forward = [list(b.succ) for b in blocks]
    join = second.join
    starts = {0} | set(blocks[join].succ)
    if second.block.index in reach(starts, {join, first.block.index}, forward):
        return False                                    # hay un camino que no pasa por `first`
    between = (reach(set(forward[first.block.index]), {join}, forward)
               & reach({second.block.index}, {join}, predecessors(blocks)))
    return not any(o.join != join and o.block.index in between
                   for o in edits if o is not first and o is not second)


def merge_redundant(edits: list[Edit], blocks: list[Block], stats: dict) -> list[Edit]:
    kept = list(edits)
    for second in sorted(edits, key=lambda e: e.block.index):
        for first in sorted(edits, key=lambda e: e.block.index):
            if any(first is k for k in kept) and any(second is k for k in kept) \
                    and is_redundant(second, first, kept, blocks):
                kept = [k for k in kept if k is not second]
                stats["ssy.merged"] = stats.get("ssy.merged", 0) + 1
                break
    return kept


def label_of(block: Block, fresh_name: Callable[[], str]) -> str:
    """El nombre de la etiqueta de `block`; si no tiene, se le pone una nueva."""
    if block.lines and block.lines[0].kind == "label":
        return block.lines[0].name
    name = fresh_name()
    block.lines.insert(0, Line("label", "", name=name))
    return name


def apply_edits(function: Function, blocks: list[Block], edits: list[Edit], stats: dict) -> None:
    """Los `SSY` se anaden de atras adelante para no mover las posiciones pendientes."""
    numbers = itertools.count(1)

    def fresh_name() -> str:
        return f"__ssy_{function.name}_{next(numbers)}"

    ordered = sorted(edits, key=lambda e: (e.block.index, -1 if e.position is None else e.position), reverse=True)
    for edit in ordered:
        ssy = instr("SSY", label_of(blocks[edit.join], fresh_name))
        if edit.position is None:
            edit.block.lines.append(ssy)
        else:
            edit.block.lines.insert(edit.position, ssy)
        stats["ssy"] = stats.get("ssy", 0) + 1


def deepest_region(function: Function) -> tuple[int, Line | None]:
    """(profundidad, SSY) del `SSY` que abre su region con mas regiones abiertas por debajo, como mucho."""
    blocks = build_cfg(function)
    block_of = {line.name: block.index for block in blocks for line in block.lines if line.kind == "label"}
    forward = [list(block.succ) for block in blocks]
    ssys = [(block.index, i, line) for block in blocks for i, line in enumerate(block.lines)
            if line.kind == "instr" and line.op == "SSY"]
    regions = []
    for b, i, line in ssys:
        join = block_of.get(line.args[0]) if line.args else None
        regions.append((b, i, reach(set(blocks[b].succ), {join} if join is not None else set(), forward)))
    deepest: tuple[int, Line | None] = (0, None)
    for k, (b, i, line) in enumerate(ssys):
        depth = 1 + sum(1 for m, (rb, ri, inside) in enumerate(regions)
                        if m != k and (b in inside or (b == rb and i > ri)))
        if depth > deepest[0]:
            deepest = (depth, line)
    return deepest


def check_depth(function: Function, where: str) -> None:
    depth, ssy = deepest_region(function)
    if depth <= MAX_REGIONS or ssy is None:
        return
    body = function.body
    after = next((line for line in body[body.index(ssy) + 1:] if line.kind == "instr"), None)
    origin = " > ".join(after.origin) if after is not None and after.origin else function.name
    raise OptError(f"{where}: hasta {depth} regiones SIMT anidadas y la GPU tiene {MAX_REGIONS} "
                   f"(el salto divergente de {origin}): hay demasiados saltos o bucles que dependen de la lane "
                   "uno dentro de otro")


@register_pass("ssy", "SSY delante de los saltos que pueden divergir (en bucles, antes del bucle)")
def pass_ssy(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if not function.name.startswith(KERNEL_PREFIX):
            continue
        where = f"{unit.path}: {function.name}"
        blocks = build_cfg(function)
        if not blocks:
            continue
        pdom = postdominators(blocks)
        div = divergent_branches(blocks, pdom)
        if not div:
            continue
        edits, handled, trampolines = loop_edits(blocks, div, pdom, where, function.name)
        edits += branch_edits(blocks, div - handled, pdom, where)
        blocks.extend(trampolines)
        apply_edits(function, blocks, merge_redundant(edits, blocks, stats), stats)
        function.body = [line for block in blocks for line in block.lines]
        check_depth(function, where)
