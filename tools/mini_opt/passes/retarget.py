"""Escribir el resultado directamente en el destino de su copia

    MIN R1, R20, R25            ->  MIN R20, R20, R25
    ADD R20, R1, R0

lcc deja en R1 lo que sale de una llamada y lo copia despues a donde lo quiere; con los intrinsecos
(`__mini_min`, `__mini_clz`... de `mini_ext.h`), que son una instruccion, esa copia es la mitad del coste.
Pasa igual con cualquier temporal: una operacion escribe `s` y la unica lectura de `s` es la copia
`ADD d, s, R0`. Se reescribe la operacion para que escriba `d` y se borra la copia si:
  - la operacion es pura y solo escribe `s` (ALU, carga, constante): moverla de registro no cambia nada mas;
  - entre las dos, en el mismo bloque, nada lee ni escribe `s` ni `d`;
  - `s` esta muerto tras la copia.
`copyprop` hace lo contrario (lleva el origen a los usos); este pase cubre el caso en el que el origen es un
registro que hay que dejar libre, como R1."""
from __future__ import annotations

from ..flow import build_cfg, live_after, liveness
from ..isa import IMM2, LOADS, R3, UNARY, WRITE_ONLY1, defs_uses, reg_of
from ..model import Unit
from ..registry import register_pass
from .copyprop import copy_of

PRODUCERS = (R3 - {"DIV", "DIVU", "REM", "REMU"}) | IMM2 | UNARY | LOADS | (WRITE_ONLY1 - {"LI"})


@register_pass("retarget", "la operacion escribe el destino de su copia (X s; ADD d, s, R0 -> X d)")
def pass_retarget(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        live_out = liveness(blocks)
        for block in blocks:
            lines = block.lines
            i = 0
            while i < len(lines):
                pair = copy_of(lines[i]) if lines[i].kind == "instr" else None
                if pair is None or retarget(lines, i, pair, live_out[block.index], block) is False:
                    i += 1
                    continue
                del lines[i]
                stats["retarget.rewritten"] = stats.get("retarget.rewritten", 0) + 1
        function.body = [line for block in blocks for line in block.lines]


def retarget(lines, i, pair, live_out, block) -> bool:
    dest, source = pair
    if source in live_after(block, live_out, i):
        return False
    for j in range(i - 1, -1, -1):
        line = lines[j]
        if line.kind != "instr":
            return False                    # una etiqueta: otro camino puede llegar a la copia
        defs, uses = defs_uses(line)
        if source in defs:
            if (line.op not in PRODUCERS or defs != {source} or not line.args
                    or reg_of(line.args[0]) != source):
                return False
            line.args[0] = f"R{dest}"
            return True
        if source in uses or dest in defs or dest in uses:
            return False
    return False
