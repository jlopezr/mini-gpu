"""Propagacion de copias y codigo muerto

lcc copia a un temporal casi todo lo que compara o indexa (`ADD R13, R28, R0 ; BGEU R13, R6, L`).
Donde la copia `d <- s` llega a un uso de `d` por todos los caminos y ni `d` ni `s` se
reescriben por el medio, el uso lee `s`; y la copia, si ya nadie lee `d`, se borra (igual que
cualquier instruccion pura cuyo resultado no se lee). Es un analisis hacia delante de copias
disponibles: la interseccion de lo que llega por cada camino. Una llamada destruye los
registros que no se conservan, asi que corta las copias de temporales."""
from __future__ import annotations

from ..dead import remove_dead
from ..flow import build_cfg, forward_must
from ..isa import defs_uses, number, reg_of, use_slots
from ..model import Line, Unit
from ..registry import register_pass


def copy_of(line: Line) -> tuple[int, int] | None:
    """(destino, origen) si la instruccion es una copia de registro."""
    if line.kind != "instr" or len(line.args) != 3:
        return None
    if line.op == "ADD" and reg_of(line.args[2]) == 0:
        pass
    elif line.op == "ADDI" and number(line.args[2]) == 0:
        pass
    else:
        return None
    dest, origin = reg_of(line.args[0]), reg_of(line.args[1])
    if dest is None or origin is None or dest == origin or dest == 0:
        return None
    return dest, origin


def is_self_copy(line: Line) -> bool:
    """`ADD d, d, R0` (o `ADDI d, d, 0`): copiar un registro a si mismo."""
    if line.kind != "instr" or len(line.args) != 3:
        return False
    d, s = reg_of(line.args[0]), reg_of(line.args[1])
    zero = (line.op == "ADD" and reg_of(line.args[2]) == 0) or (line.op == "ADDI" and number(line.args[2]) == 0)
    return zero and d is not None and d == s and d != 0


def track_copies(state: dict[int, int], line: Line) -> None:
    """Actualiza las copias vigentes `{destino: origen}` tras ejecutar `line`."""
    for written in defs_uses(line)[0]:
        for key in [k for k, v in state.items() if k == written or v == written]:
            del state[key]
    pair = copy_of(line)
    if pair is not None:
        state[pair[0]] = pair[1]


@register_pass("copyprop", "propagacion de copias (ADD d, s, R0) y borrado de lo que ya nadie lee")
def pass_copyprop(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        blocks = build_cfg(function)
        if not blocks:
            continue
        for block, entering in zip(blocks, forward_must(blocks, track_copies)):
            state = dict(entering)
            keep = []
            for line in block.lines:
                if line.kind != "instr":
                    keep.append(line)
                    continue
                for slot in use_slots(line) or []:
                    origin = state.get(reg_of(line.args[slot]) or 0)
                    if origin is not None:
                        line.args[slot] = f"R{origin}"
                        stats["copyprop.rewritten"] = stats.get("copyprop.rewritten", 0) + 1
                if is_self_copy(line):                       # `ADD R14, R31, R0` con R31 = R14: ya no hace nada
                    stats["copyprop.removed"] = stats.get("copyprop.removed", 0) + 1
                    continue
                keep.append(line)
                track_copies(state, line)
            block.lines = keep
        remove_dead(blocks, stats, "copyprop")
        function.body = [line for block in blocks for line in block.lines]
