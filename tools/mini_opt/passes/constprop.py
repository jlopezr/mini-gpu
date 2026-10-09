"""Propagacion de constantes

Donde un registro vale una constante por todos los caminos (`MOVI R7, 256`), la instruccion que
lo lee pasa a su forma con inmediato: `SUB d, a, R7` -> `ADDI d, a, -256`; `ADD`, `AND`, `OR` y
`XOR` igual (la suma con signo de 16 bits, la logica sin signo). Un desplazamiento de 1 bit es
una suma: `SHL d, a, R9` con R9 = 1 -> `ADD d, a, a`. La constante deja de ocupar un registro
(la GPU no tiene saltos ni desplazamientos con inmediato, asi que no todas se van)."""
from __future__ import annotations

from ..flow import build_cfg, forward_must
from ..isa import R3, defs_uses, number, reg_of
from ..model import Line, Unit
from ..registry import register_pass

FOLD_LOGIC = {"AND": "ANDI", "OR": "ORI", "XOR": "XORI"}
SIGNED_16 = range(-32768, 32768)
UNSIGNED_16 = range(0, 0x10000)


def constant_of(line: Line) -> int | None:
    """Valor que deja en su destino una instruccion que carga una constante numerica."""
    if line.kind != "instr" or len(line.args) < 2:
        return None
    if line.op in ("MOVI", "LI"):
        return number(line.args[1])
    if line.op == "ADDI" and reg_of(line.args[1]) == 0:
        return number(line.args[2])
    return None


def track_constants(state: dict[int, int], line: Line) -> None:
    """Actualiza las constantes vigentes `{registro: valor}` tras ejecutar `line`."""
    for written in defs_uses(line)[0]:
        state.pop(written, None)
    value = constant_of(line)
    dest = reg_of(line.args[0]) if value is not None else None
    if value is not None and dest:                  # None y R0 no cuentan
        state[dest] = value


def fold_constant(line: Line, state: dict[int, int]) -> bool:
    """Reescribe `line` con inmediato si un operando es una constante conocida."""
    if line.op not in R3 or len(line.args) != 3:
        return False
    d, a, b = line.args
    ra, rb = reg_of(a), reg_of(b)
    ca = state.get(ra) if ra else None
    cb = state.get(rb) if rb else None
    if line.op == "ADD":
        if cb is not None and cb in SIGNED_16:
            line.op, line.args = "ADDI", [d, a, str(cb)]
        elif ca is not None and ca in SIGNED_16:
            line.op, line.args = "ADDI", [d, b, str(ca)]
        else:
            return False
    elif line.op == "SUB" and cb is not None and -cb in SIGNED_16:
        line.op, line.args = "ADDI", [d, a, str(-cb)]
    elif line.op in FOLD_LOGIC:
        if cb is not None and cb in UNSIGNED_16:
            line.op, line.args = FOLD_LOGIC[line.op], [d, a, str(cb)]
        elif ca is not None and ca in UNSIGNED_16:
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
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        for block, entering in zip(blocks, forward_must(blocks, track_constants)):
            state = dict(entering)
            for line in block.lines:
                if line.kind != "instr":
                    continue
                if fold_constant(line, state):
                    stats["constprop.folded"] = stats.get("constprop.folded", 0) + 1
                track_constants(state, line)
        function.body = [line for block in blocks for line in block.lines]
