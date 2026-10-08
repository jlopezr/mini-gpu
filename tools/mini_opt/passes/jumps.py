"""Saltos encadenados: `Lx: BRA Ly` -> los que saltan a Lx saltan a Ly

lcc cierra cada `if/else` anidado con su propia etiqueta que solo salta a la de fuera. Para el
flujo es lo mismo, pero cada una es un postdominador distinto, y el pase `ssy` abre una
region por cada uno. Con las cadenas deshechas todos los caminos reconvergen en el mismo punto."""
from __future__ import annotations

from ..isa import BRANCHES
from ..model import Line, Unit
from ..registry import register_pass


def jump_only_labels(body: list[Line]) -> dict[str, str]:
    """Etiqueta -> destino, para las etiquetas cuyo codigo es solo `BRA destino`."""
    forward: dict[str, str] = {}
    for i, line in enumerate(body):
        if line.kind != "label":
            continue
        j = i + 1
        while j < len(body) and body[j].kind == "label":
            j += 1
        if j < len(body) and body[j].kind == "instr" and body[j].op == "BRA" and len(body[j].args) == 1:
            forward[line.name] = body[j].args[0]
    return forward


def final_target(label: str, forward: dict[str, str]) -> str:
    """El destino al final de una cadena de `BRA` (sin dar vueltas si hay un ciclo)."""
    seen = {label}
    while label in forward and forward[label] not in seen:
        label = forward[label]
        seen.add(label)
    return label


def drop_jumps_to_next_line(body: list[Line], stats: dict) -> list[Line]:
    """Un `BRA` a una etiqueta que viene justo despues salta a donde ya iba a caer."""
    kept: list[Line] = []
    for i, line in enumerate(body):
        if line.kind == "instr" and line.op == "BRA":
            following = set()
            j = i + 1
            while j < len(body) and body[j].kind == "label":
                following.add(body[j].name)
                j += 1
            if line.args[-1] in following:
                stats["jumps.removed"] = stats.get("jumps.removed", 0) + 1
                continue
        kept.append(line)
    return kept


@register_pass("jumps", "BRA a una etiqueta que solo salta: salta al destino final; quita el BRA a la linea siguiente")
def pass_jumps(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        forward = jump_only_labels(function.body)
        for line in function.body:
            if line.kind == "instr" and (line.op in BRANCHES or line.op == "BRA"):
                target = final_target(line.args[-1], forward)
                if target != line.args[-1]:
                    line.args[-1] = target
                    stats["jumps.threaded"] = stats.get("jumps.threaded", 0) + 1
        function.body = drop_jumps_to_next_line(function.body, stats)
