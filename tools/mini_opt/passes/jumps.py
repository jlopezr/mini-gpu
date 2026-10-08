"""Saltos encadenados: `Lx: BRA Ly` -> los que saltan a Lx saltan a Ly

lcc cierra cada `if/else` anidado con su propia etiqueta que solo salta a la de fuera. Para el
flujo es lo mismo, pero cada una es un postdominador distinto, y el pase `ssy` abre una
region por cada uno. Con las cadenas deshechas todos los caminos reconvergen en el mismo punto."""
from __future__ import annotations

from ..isa import BRANCHES
from ..model import Line, Unit
from ..registry import register_pass


@register_pass("jumps", "BRA a una etiqueta que solo salta: salta al destino final; quita el BRA a la linea siguiente")
def pass_jumps(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        body = function.body
        forward: dict[str, str] = {}                  # etiqueta -> destino, si su codigo es `BRA destino`
        for i, line in enumerate(body):
            if line.kind != "label":
                continue
            j = i + 1
            while j < len(body) and body[j].kind == "label":
                j += 1
            if j < len(body) and body[j].kind == "instr" and body[j].op == "BRA" and len(body[j].args) == 1:
                forward[line.name] = body[j].args[0]

        def final(label: str) -> str:
            seen = {label}
            while label in forward and forward[label] not in seen:
                label = forward[label]
                seen.add(label)
            return label

        for line in body:
            if line.kind == "instr" and (line.op in BRANCHES or line.op == "BRA"):
                target = line.args[-1]
                new = final(target)
                if new != target:
                    line.args[-1] = new
                    stats["jumps.threaded"] = stats.get("jumps.threaded", 0) + 1
        kept: list[Line] = []
        for i, line in enumerate(body):
            if line.kind == "instr" and line.op == "BRA":
                j = i + 1
                names = set()
                while j < len(body) and body[j].kind == "label":
                    names.add(body[j].name)
                    j += 1
                if line.args[-1] in names:                # salta a donde ya iba a caer
                    stats["jumps.removed"] = stats.get("jumps.removed", 0) + 1
                    continue
            kept.append(line)
        function.body = kept
