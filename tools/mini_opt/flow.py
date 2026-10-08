"""Bloques basicos, vida de registros, dominadores, postdominadores y bucles naturales."""
from __future__ import annotations

from dataclasses import dataclass, field

from .isa import BRANCHES, defs_uses
from .model import Function, Line, OptError


@dataclass
class Block:
    index: int
    lines: list[Line]
    succ: list[int] = field(default_factory=list)


def label_target(line: Line) -> str:
    return line.args[-1]


def build_cfg(function: Function) -> list[Block]:
    """Bloques basicos de una funcion. Salta hacia fuera (a otra funcion) no
    genera arista. `BRA`, `EXIT`, `HALT`, `JR` terminan sin continuar."""
    blocks: list[Block] = []
    current: list[Line] = []
    for line in function.body:
        if line.kind == "label" and any(l.kind != "label" for l in current):   # varias etiquetas seguidas: un bloque
            blocks.append(Block(len(blocks), current))
            current = []
        current.append(line)
        if line.kind == "instr" and (line.op in BRANCHES or line.op in
                                     ("BRA", "EXIT", "HALT", "TRAP", "JR")):
            blocks.append(Block(len(blocks), current))
            current = []
    if current:
        blocks.append(Block(len(blocks), current))
    at = {}
    for block in blocks:
        for line in block.lines:
            if line.kind == "label":
                at[line.name] = block.index
    for block in blocks:
        last = next((l for l in reversed(block.lines) if l.kind == "instr"), None)
        falls = last is None or last.op not in ("BRA", "EXIT", "HALT", "TRAP", "JR")
        if last is not None and (last.op in BRANCHES or last.op == "BRA"):
            target = label_target(last)
            if target in at:
                block.succ.append(at[target])
        if falls and block.index + 1 < len(blocks):
            block.succ.append(block.index + 1)
    return blocks


def liveness(blocks: list[Block]) -> list[set[int]]:
    """Registros vivos a la salida de cada bloque (analisis hacia atras)."""
    live_in = [set() for _ in blocks]
    live_out = [set() for _ in blocks]
    changed = True
    while changed:
        changed = False
        for block in reversed(blocks):
            out = set().union(*(live_in[s] for s in block.succ)) if block.succ else set()
            live = set(out)
            for line in reversed(block.lines):
                if line.kind == "instr":
                    defs, uses = defs_uses(line)
                    live = (live - defs) | uses
            if out != live_out[block.index] or live != live_in[block.index]:
                live_out[block.index], live_in[block.index] = out, live
                changed = True
    return live_out


def live_after(block: Block, live_out: set[int], position: int) -> set[int]:
    """Registros vivos justo despues de `block.lines[position]`."""
    live = set(live_out)
    for line in reversed(block.lines[position + 1:]):
        if line.kind == "instr":
            defs, uses = defs_uses(line)
            live = (live - defs) | uses
    return live


def free_register(busy: set[int], where: str) -> int:
    """Un temporal de R5..R15 que no este en `busy`. R5 y R6 son los scratch del
    backend (nunca los asigna el compilador), asi que casi siempre hay uno."""
    for r in range(5, 16):
        if r not in busy:
            return r
    raise OptError(f"{where}: no queda ningun registro libre para una expansion")


def live_in_entry(blocks: list[Block], live_out: list[set[int]]) -> set[int]:
    """Registros que la funcion lee antes de escribirlos (vivos a la entrada)."""
    return live_after(Block(-1, [Line("directive", "")] + blocks[0].lines), live_out[0], 0)


def live_in_blocks(blocks: list[Block], live_out: list[set[int]]) -> list[set[int]]:
    result = []
    for block in blocks:
        live = set(live_out[block.index])
        for line in reversed(block.lines):
            if line.kind == "instr":
                defs, uses = defs_uses(line)
                live = (live - defs) | uses
        result.append(live)
    return result


def postdominators(blocks: list[Block]) -> list[set[int]]:
    """pdom[b] = bloques que estan en todo camino de b a la salida (incluido b). El
    indice len(blocks) es la salida virtual."""
    n = len(blocks)
    pdom = [set(range(n + 1)) for _ in range(n)] + [{n}]
    changed = True
    while changed:
        changed = False
        for b in reversed(range(n)):
            succ = blocks[b].succ or [n]
            new = set.intersection(*(pdom[s] for s in succ)) | {b}
            if new != pdom[b]:
                pdom[b], changed = new, True
    return pdom


def immediate_postdominator(pdom: list[set[int]], b: int) -> int:
    strict = pdom[b] - {b}
    return max(strict, key=lambda p: len(pdom[p]))     # la cadena de postdominadores: el mas cercano


def dominators(blocks: list[Block]) -> list[set[int]]:
    n = len(blocks)
    dom = [set(range(n)) for _ in range(n)]
    dom[0] = {0}
    preds: list[list[int]] = [[] for _ in range(n)]
    for block in blocks:
        for s in block.succ:
            preds[s].append(block.index)
    changed = True
    while changed:
        changed = False
        for b in range(1, n):
            if not preds[b]:
                continue
            new = set.intersection(*(dom[p] for p in preds[b])) | {b}
            if new != dom[b]:
                dom[b], changed = new, True
    return dom


def natural_loops(blocks: list[Block], dom: list[set[int]]) -> dict[int, set[int]]:
    """cabecera -> cuerpo, uniendo los bucles que comparten cabecera."""
    preds: list[list[int]] = [[] for _ in blocks]
    for block in blocks:
        for s in block.succ:
            preds[s].append(block.index)
    loops: dict[int, set[int]] = {}
    for block in blocks:
        for h in block.succ:
            if h in dom[block.index]:                       # arista de vuelta u -> h
                body = loops.setdefault(h, {h})
                stack = [block.index]
                while stack:
                    x = stack.pop()
                    if x not in body:
                        body.add(x)
                        stack.extend(preds[x])
    return loops
