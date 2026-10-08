"""Codigo muerto: instrucciones puras cuyo resultado nadie lee (lo usan `constprop` y `copyprop`)."""
from __future__ import annotations

from .flow import Block, live_after, liveness
from .isa import PURE_OPS, defs_uses
from .model import Line

DEAD_OK = PURE_OPS


def remove_dead(blocks: list[Block], stats: dict, name: str) -> None:
    """Borra las instrucciones puras cuyo resultado no se lee, hasta que no quede ninguna."""
    while True:
        live_out = liveness(blocks)
        removed = 0
        for block in blocks:
            keep: list[Line] = []
            for position, line in enumerate(block.lines):
                if line.kind == "instr" and line.op in DEAD_OK:
                    defs, _ = defs_uses(line)
                    if len(defs) == 1 and not defs & live_after(block, live_out[block.index], position):
                        removed += 1
                        continue
                keep.append(line)
            block.lines = keep
            if removed:
                break                                 # la vida cambio: recalcular
        if not removed:
            return
        stats[f"{name}.removed"] = stats.get(f"{name}.removed", 0) + removed
