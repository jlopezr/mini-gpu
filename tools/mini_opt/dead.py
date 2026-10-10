"""Motor de codigo muerto para el pase independiente `dce`."""
from __future__ import annotations

from .flow import Block, liveness
from .isa import GETID, PURE_OPS, defs_uses
from .model import Line

DEAD_OK = PURE_OPS | GETID        # leer el id del hilo o el bloque de argumentos no tiene efectos


def remove_dead(blocks: list[Block], stats: dict, name: str) -> None:
    """Borra las instrucciones puras cuyo resultado no se lee, hasta que no quede ninguna.

    Cada vuelta calcula la vida de registros una vez y recorre cada bloque hacia atras, llevando los
    registros vivos: una instruccion que se borra no los alimenta, asi que las cadenas dentro de un bloque
    caen de una pasada. Lo que depende de otro bloque cae en la vuelta siguiente."""
    while True:
        live_out = liveness(blocks)
        removed = 0
        for block in blocks:
            live = set(live_out[block.index])
            keep: list[Line] = []
            for line in reversed(block.lines):
                if line.kind == "instr":
                    defs, uses = defs_uses(line)
                    if line.op in DEAD_OK and len(defs) == 1 and not defs & live:
                        removed += 1
                        continue
                    live = (live - defs) | uses
                keep.append(line)
            keep.reverse()
            block.lines = keep
        if not removed:
            return
        stats[f"{name}.removed"] = stats.get(f"{name}.removed", 0) + removed
