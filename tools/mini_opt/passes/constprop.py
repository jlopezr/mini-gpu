"""Propagacion de constantes

Donde un registro vale una constante por todos los caminos (`MOVI R7, 256`), la instruccion que
lo lee pasa a su forma con inmediato: `SUB d, a, R7` -> `ADDI d, a, -256`; `ADD`, `AND`, `OR` y
`XOR` igual (la suma con signo de 16 bits, la logica sin signo). Un desplazamiento de 1 bit es
una suma: `SHL d, a, R9` con R9 = 1 -> `ADD d, a, a`. La constante deja de ocupar un registro
(la GPU no tiene saltos ni desplazamientos con inmediato, asi que no todas se van)."""
from __future__ import annotations

from ..dead import remove_dead
from ..flow import Block, build_cfg
from ..isa import R3, defs_uses, number, reg_of
from ..model import Line, Unit
from ..registry import register_pass


FOLD_LOGIC = {"AND": "ANDI", "OR": "ORI", "XOR": "XORI"}


def constant_of(line: Line) -> int | None:
    """Valor que deja en su destino una instruccion que carga una constante numerica."""
    if line.kind != "instr" or not line.args:
        return None
    if line.op in ("MOVI", "LI"):
        return number(line.args[1])
    if line.op == "ADDI" and reg_of(line.args[1]) == 0:
        return number(line.args[2])
    return None


def known_constants(blocks: list[Block]) -> list[dict[int, int] | None]:
    """Constantes {registro: valor} que valen a la entrada de cada bloque (interseccion por los caminos)."""
    n = len(blocks)
    preds: list[list[int]] = [[] for _ in range(n)]
    for block in blocks:
        for s in block.succ:
            preds[s].append(block.index)

    def step(state: dict[int, int], line: Line) -> None:
        for reg in defs_uses(line)[0]:
            state.pop(reg, None)
        value = constant_of(line)
        if value is not None and reg_of(line.args[0]) not in (None, 0):
            state[reg_of(line.args[0])] = value

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


def fold_constant(line: Line, state: dict[int, int]) -> bool:
    """Reescribe `line` con inmediato si un operando es una constante conocida."""
    if line.op not in R3 or len(line.args) != 3:
        return False
    d, a, b = line.args
    ra, rb = reg_of(a), reg_of(b)
    ca = state.get(ra) if ra not in (None, 0) else None
    cb = state.get(rb) if rb not in (None, 0) else None
    if line.op == "ADD":
        if cb is not None and -32768 <= cb <= 32767:
            line.op, line.args = "ADDI", [d, a, str(cb)]
        elif ca is not None and -32768 <= ca <= 32767:
            line.op, line.args = "ADDI", [d, b, str(ca)]
        else:
            return False
    elif line.op == "SUB" and cb is not None and -32768 <= -cb <= 32767:
        line.op, line.args = "ADDI", [d, a, str(-cb)]
    elif line.op in FOLD_LOGIC:
        if cb is not None and 0 <= cb <= 0xFFFF:
            line.op, line.args = FOLD_LOGIC[line.op], [d, a, str(cb)]
        elif ca is not None and 0 <= ca <= 0xFFFF:
            line.op, line.args = FOLD_LOGIC[line.op], [d, b, str(ca)]
        else:
            return False
    elif line.op == "SHL" and cb == 1:
        line.op, line.args = "ADD", [d, a, a]
    else:
        return False
    return True


@register_pass("constprop", "constantes conocidas: ADD/SUB/AND/OR/XOR a su forma con inmediato, SHL por 1 a ADD")
def pass_constprop(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        blocks = build_cfg(function)
        if not blocks:
            continue
        entry = known_constants(blocks)
        for b, block in enumerate(blocks):
            state = dict(entry[b] or {})
            for line in block.lines:
                if line.kind != "instr":
                    continue
                if fold_constant(line, state):
                    stats["constprop.folded"] = stats.get("constprop.folded", 0) + 1
                for reg in defs_uses(line)[0]:
                    state.pop(reg, None)
                value = constant_of(line)
                if value is not None and reg_of(line.args[0]) not in (None, 0):
                    state[reg_of(line.args[0])] = value
        remove_dead(blocks, stats, "constprop")
        function.body = [line for block in blocks for line in block.lines]
