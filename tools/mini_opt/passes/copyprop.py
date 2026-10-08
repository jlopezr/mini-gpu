"""Propagacion de copias y codigo muerto

lcc copia a un temporal casi todo lo que compara o indexa (`ADD R13, R28, R0 ; BGEU R13, R6, L`).
Donde la copia `d <- s` llega a un uso de `d` por todos los caminos y ni `d` ni `s` se
reescriben por el medio, el uso lee `s`; y la copia, si ya nadie lee `d`, se borra (igual que
cualquier instruccion pura cuyo resultado no se lee). Es un analisis hacia delante de copias
disponibles: la interseccion de lo que llega por cada camino. Una llamada destruye los
registros que no se conservan, asi que corta las copias de temporales."""
from __future__ import annotations

from ..dead import remove_dead
from ..flow import Block, build_cfg
from ..isa import defs_uses, number, reg_of, use_slots
from ..model import Line, Unit
from ..registry import register_pass


def copy_of(line: Line) -> tuple[int, int] | None:
    """(destino, origen) si la instruccion es una copia de registro."""
    if line.kind != "instr":
        return None
    if line.op == "ADD" and len(line.args) == 3 and reg_of(line.args[2]) == 0:
        d, s = reg_of(line.args[0]), reg_of(line.args[1])
    elif line.op == "ADDI" and len(line.args) == 3 and number(line.args[2]) == 0:
        d, s = reg_of(line.args[0]), reg_of(line.args[1])
    else:
        return None
    return (d, s) if d is not None and s is not None and d != s and d != 0 else None


def available_copies(blocks: list[Block]) -> list[dict[int, int] | None]:
    """Copias {destino: origen} que valen a la entrada de cada bloque (None = aun sin calcular)."""
    n = len(blocks)
    preds: list[list[int]] = [[] for _ in range(n)]
    for block in blocks:
        for s in block.succ:
            preds[s].append(block.index)

    def step(state: dict[int, int], line: Line) -> None:
        defs, _ = defs_uses(line)
        for reg in defs:
            for key in [k for k, v in state.items() if k == reg or v == reg]:
                del state[key]
        pair = copy_of(line)
        if pair is not None:
            state[pair[0]] = pair[1]

    entry: list[dict[int, int] | None] = [None] * n
    out: list[dict[int, int] | None] = [None] * n
    entry[0] = {}
    changed = True
    while changed:
        changed = False
        for b in range(n):
            if b != 0:
                known = [out[p] for p in preds[b] if out[p] is not None]
                if not known:
                    continue
                new = {k: v for k, v in known[0].items() if all(o.get(k) == v for o in known[1:])}
                if entry[b] != new:
                    entry[b], changed = new, True
            state = dict(entry[b] or {})
            for line in blocks[b].lines:
                if line.kind == "instr":
                    step(state, line)
            if out[b] != state:
                out[b], changed = state, True
    return entry


@register_pass("copyprop", "propagacion de copias (ADD d, s, R0) y borrado de lo que ya nadie lee")
def pass_copyprop(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        blocks = build_cfg(function)
        if not blocks:
            continue
        entry = available_copies(blocks)
        for b, block in enumerate(blocks):
            state = dict(entry[b] or {})
            for line in block.lines:
                if line.kind != "instr":
                    continue
                slots = use_slots(line)
                for i in slots or []:
                    reg = reg_of(line.args[i])
                    if reg in state:
                        line.args[i] = f"R{state[reg]}"
                        stats["copyprop.rewritten"] = stats.get("copyprop.rewritten", 0) + 1
                defs, _ = defs_uses(line)
                for reg in defs:
                    for key in [k for k, v in state.items() if k == reg or v == reg]:
                        del state[key]
                pair = copy_of(line)
                if pair is not None:
                    state[pair[0]] = pair[1]
        remove_dead(blocks, stats, "copyprop")
        function.body = [line for block in blocks for line in block.lines]
