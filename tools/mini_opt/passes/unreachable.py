"""Elimina bloques que no son alcanzables desde la entrada de la funcion."""
from __future__ import annotations

from ..flow import build_cfg
from ..model import Unit
from ..registry import register_pass


@register_pass("unreachable", "borra bloques e instrucciones no alcanzables desde la entrada")
def pass_unreachable(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        reached: set[int] = set()
        pending = [0]
        while pending:
            index = pending.pop()
            if index in reached:
                continue
            reached.add(index)
            pending.extend(blocks[index].succ)
        dead = [block for block in blocks if block.index not in reached]
        if not dead:
            continue
        stats["unreachable.blocks"] = stats.get("unreachable.blocks", 0) + len(dead)
        stats["unreachable.removed"] = stats.get("unreachable.removed", 0) + sum(
            line.kind == "instr" for block in dead for line in block.lines
        )
        function.body = [
            line for block in blocks if block.index in reached for line in block.lines
        ]
