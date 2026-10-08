"""SSY automatico: donde reconvergen los caminos de un salto divergente

Un salto condicional cuyas lanes toman caminos distintos necesita una region
abierta con `SSY join` (isa.md): sin ella el SM para con ERROR_SIMT. `join` es el
postdominador inmediato del salto, el primer punto por el que pasan todos los
caminos. En un bucle cuyas lanes salen en vueltas distintas, la region se abre
una vez antes del bucle (en el preheader), con el punto de salida como join; asi
valen tanto el salto de vuelta como cualquier `break`.

Solo hace falta para los saltos que PUEDEN divergir. Un valor varia entre lanes si
viene de GETTID o GETLANE (o de una pila, que es de cada lane) y se propaga por la
aritmetica y las cargas; lo que se define bajo un salto divergente tambien varia.
Con `SSY_ALL` se trata todo salto condicional como divergente."""
from __future__ import annotations

from ..flow import Block, build_cfg, dominators, immediate_postdominator, natural_loops, postdominators
from ..isa import BRANCHES, LOADS, STACK, defs_uses, instr, reg_of
from ..model import Line, OptError, Unit
from .kernels import KERNEL_PREFIX
from ..registry import register_pass


SSY_ALL = False

VARYING_SOURCES = {"GETTID", "GETLANE"}

UNIFORM_SOURCES = {"MOVI", "MOVHI", "LI", "GETWARP", "GETLWARP", "GETARG"}


def divergent_branches(blocks: list[Block], pdom: list[set[int]]) -> set[int]:
    """Indices de los bloques cuyo salto condicional puede divergir."""
    n = len(blocks)
    last = {b.index: next((l for l in reversed(b.lines) if l.kind == "instr"), None) for b in blocks}
    conditional = {i for i, l in last.items() if l is not None and l.op in BRANCHES}
    if SSY_ALL:
        return conditional
    tainted: set[int] = set()
    while True:
        var_in = [set() for _ in range(n)]
        changed = True
        while changed:
            changed = False
            for block in blocks:
                var = set(var_in[block.index])
                for line in block.lines:
                    if line.kind != "instr":
                        continue
                    defs, uses = defs_uses(line)
                    if not defs:
                        continue
                    if line.op in VARYING_SOURCES or block.index in tainted:
                        varying = True
                    elif line.op in UNIFORM_SOURCES:
                        varying = False
                    elif line.op in LOADS:
                        base = reg_of(line.args[1])
                        varying = base == STACK or base in var       # direccion distinta = dato distinto
                    else:
                        varying = bool(uses & var)
                    var = (var | defs) if varying else (var - defs)
                for s in block.succ:
                    if not var <= var_in[s]:
                        var_in[s] |= var
                        changed = True
        found: set[int] = set()
        for block in blocks:
            if block.index not in conditional:
                continue
            var = set(var_in[block.index])
            for line in block.lines[:-1]:
                if line.kind == "instr":
                    defs, uses = defs_uses(line)
                    if line.op in VARYING_SOURCES or block.index in tainted:
                        v = True
                    elif line.op in UNIFORM_SOURCES:
                        v = False
                    elif line.op in LOADS:
                        v = reg_of(line.args[1]) == STACK or reg_of(line.args[1]) in var
                    else:
                        v = bool(uses & var)
                    if defs:
                        var = (var | defs) if v else (var - defs)
            branch = last[block.index]
            if any(reg_of(a) in var for a in branch.args[:2] if reg_of(a) is not None):
                found.add(block.index)
        # lo que se ejecuta bajo un salto divergente es de unas lanes y no de otras
        region: set[int] = set()
        for b in found:
            join = immediate_postdominator(pdom, b)
            stack = list(blocks[b].succ)
            while stack:
                x = stack.pop()
                if x == join or x in region:
                    continue
                region.add(x)
                stack.extend(blocks[x].succ)
        if region <= tainted:
            return found
        tainted |= region


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
        dom = dominators(blocks)
        div = divergent_branches(blocks, pdom)
        if not div:
            continue
        count = [0]

        def label_of(index: int) -> str:
            block = blocks[index]
            if block.lines and block.lines[0].kind == "label":
                return block.lines[0].name
            count[0] += 1
            name = f"__ssy_{function.name}_{count[0]}"
            block.lines.insert(0, Line("label", "", name=name))
            return name

        def common_postdominator(targets: list[int]) -> int:
            common = set.intersection(*(pdom[t] for t in targets))
            if not common:
                raise OptError(f"{where}: no encuentro donde reconvergen las salidas de un bucle")
            return max(common, key=lambda p: len(pdom[p]))

        handled: set[int] = set()
        edits: list[tuple[Block, int | None, int]] = []       # (bloque, posicion o None=al final, join)
        preds: list[list[int]] = [[] for _ in blocks]
        for block in blocks:
            for s in block.succ:
                preds[s].append(block.index)
        for header, body in sorted(natural_loops(blocks, dom).items()):
            exits = [b for b in body if b in div and any(s not in body for s in blocks[b].succ)]
            if not exits:
                continue
            targets = sorted({s for b in exits for s in blocks[b].succ if s not in body})
            join = targets[0] if len(targets) == 1 else common_postdominator(targets)
            for b in exits:
                if immediate_postdominator(pdom, b) == join:
                    handled.add(b)
            if not any(b in handled for b in exits):
                continue
            for p in preds[header]:
                if p in body:
                    continue
                term = next((l for l in reversed(blocks[p].lines) if l.kind == "instr"), None)
                pos = None
                if term is not None and term.op == "BRA":
                    pos = max(i for i, l in enumerate(blocks[p].lines) if l is term)
                elif term is not None and (term.op in BRANCHES or term.op in ("EXIT", "HALT", "JR")):
                    raise OptError(f"{where}: la entrada a un bucle con divergencia sale de un salto "
                                   "condicional; no se sabe donde abrir su region")
                edits.append((blocks[p], pos, join))
        for b in sorted(div - handled):
            join = immediate_postdominator(pdom, b)
            if join >= len(blocks):
                raise OptError(f"{where}: un salto divergente no reconverge antes de salir del kernel")
            edits.append((blocks[b], len(blocks[b].lines) - 1, join))
        # un `SSY` que cae siempre despues de otro con el mismo destino sobra: la region ya esta abierta
        # (y puede divergir mas de un salto dentro de ella, como en un `if/else if`). Se conserva si por
        # el camino se abre otra region con otro destino, que seria la mas interna.
        def reach(starts: set[int], avoid: set[int], edges) -> set[int]:
            seen: set[int] = set()
            stack = [s for s in starts if s not in avoid]
            while stack:
                x = stack.pop()
                if x in seen or x in avoid:
                    continue
                seen.add(x)
                stack.extend(edges[x])
            return seen

        forward = [list(b.succ) for b in blocks]
        edges_sorted = sorted(edits, key=lambda e: e[0].index)
        for e2 in edges_sorted:
            for e1 in edges_sorted:
                if not any(e2 is a for a in edits):
                    break
                if e1 is e2 or e1[2] != e2[2] or e1[0].index == e2[0].index or not any(e1 is a for a in edits):
                    continue
                join = e2[2]
                starts = {0} | set(blocks[join].succ)
                if e2[0].index in reach(starts, {join, e1[0].index}, forward):
                    continue                                    # hay un camino que no pasa por e1
                between = (reach(set(forward[e1[0].index]), {join}, forward)
                           & reach({e2[0].index}, {join}, preds))
                if any(o[2] != join and o[0].index in between for o in edits if o is not e1 and o is not e2):
                    continue
                edits[:] = [e for e in edits if e is not e2]
                stats["ssy.merged"] = stats.get("ssy.merged", 0) + 1
                break
        # los `SSY` se anaden de atras adelante para no mover las posiciones pendientes
        for block, pos, join in sorted(edits, key=lambda e: (e[0].index, -1 if e[1] is None else e[1]),
                                       reverse=True):
            ssy = instr("SSY", label_of(join))
            if pos is None:
                block.lines.append(ssy)
            else:
                block.lines.insert(pos, ssy)
            stats["ssy"] = stats.get("ssy", 0) + 1
        function.body = [line for block in blocks for line in block.lines]
