"""Eliminacion independiente de resultados puros que ya no estan vivos."""
from __future__ import annotations

from ..dead import remove_dead
from ..flow import build_cfg
from ..model import Unit
from ..registry import register_pass


@register_pass("dce", "borra instrucciones puras cuyo resultado no esta vivo")
def pass_dce(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        remove_dead(blocks, stats, "dce")
        function.body = [line for block in blocks for line in block.lines]
