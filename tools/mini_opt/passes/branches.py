"""Branches cuyo resultado se conoce por constantes o por identidad."""
from __future__ import annotations

from ..flow import build_cfg, forward_must
from ..isa import BRANCHES, reg_of
from ..model import Line, Unit
from ..registry import register_pass
from .constprop import track_constants


def u32(value: int) -> int:
    return value & 0xFFFFFFFF


def s32(value: int) -> int:
    value = u32(value)
    return value - 0x100000000 if value & 0x80000000 else value


def known_branch(line: Line, constants: dict[int, int]) -> bool | None:
    if line.op not in BRANCHES or len(line.args) != 3:
        return None
    left, right = reg_of(line.args[0]), reg_of(line.args[1])
    if left is None or right is None:
        return None
    if left == right:
        return line.op in ("BEQ", "BGE", "BGEU")
    a = 0 if left == 0 else constants.get(left)
    b = 0 if right == 0 else constants.get(right)
    if a is None or b is None:
        return None
    if line.op == "BEQ":
        return u32(a) == u32(b)
    if line.op == "BNE":
        return u32(a) != u32(b)
    if line.op == "BLT":
        return s32(a) < s32(b)
    if line.op == "BGE":
        return s32(a) >= s32(b)
    if line.op == "BLTU":
        return u32(a) < u32(b)
    if line.op == "BGEU":
        return u32(a) >= u32(b)
    return None


@register_pass("branches", "branches constantes/identicos: siempre -> BRA, nunca -> se borra")
def pass_branches(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        for block, entering in zip(blocks, forward_must(blocks, track_constants)):
            state = dict(entering)
            rewritten: list[Line] = []
            for line in block.lines:
                result = known_branch(line, state) if line.kind == "instr" else None
                if result is True:
                    rewritten.append(Line("instr", "", op="BRA", args=[line.args[-1]]))
                    stats["branches.taken"] = stats.get("branches.taken", 0) + 1
                elif result is False:
                    stats["branches.removed"] = stats.get("branches.removed", 0) + 1
                else:
                    rewritten.append(line)
                if line.kind == "instr":
                    track_constants(state, line)
            block.lines = rewritten
        function.body = [line for block in blocks for line in block.lines]
