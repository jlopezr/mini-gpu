"""Bloques basicos, vida de registros, dominadores, postdominadores y bucles naturales."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .isa import BRANCHES, defs_uses
from .model import Function, Line, OptError

V = TypeVar("V")


@dataclass
class Block:
    index: int
    lines: list[Line]
    succ: list[int] = field(default_factory=list)

    def last_instr(self) -> Line | None:
        """La ultima instruccion del bloque (la que lo termina, si salta)."""
        return next((l for l in reversed(self.lines) if l.kind == "instr"), None)


def predecessors(blocks: list[Block]) -> list[list[int]]:
    preds: list[list[int]] = [[] for _ in blocks]
    for block in blocks:
        for s in block.succ:
            preds[s].append(block.index)
    return preds


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
        last = block.last_instr()
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
    # lo que cada bloque lee antes de escribirlo (gen) y lo que escribe (kill), una sola vez
    gen: list[frozenset[int]] = []
    kill: list[frozenset[int]] = []
    for block in blocks:
        read: set[int] = set()
        written: set[int] = set()
        for line in reversed(block.lines):
            if line.kind == "instr":
                defs, uses = defs_uses(line)
                read = (read - defs) | uses
                written |= defs
        gen.append(frozenset(read))
        kill.append(frozenset(written))
    live_in = [set(g) for g in gen]
    live_out = [set() for _ in blocks]
    changed = True
    while changed:
        changed = False
        for block in reversed(blocks):
            index = block.index
            out = set().union(*(live_in[s] for s in block.succ)) if block.succ else set()
            live = gen[index] | (out - kill[index])
            if out != live_out[index] or live != live_in[index]:
                live_out[index], live_in[index] = out, live
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


def forward_must(blocks: list[Block], step: Callable[[dict[int, V], Line], None]) -> list[dict[int, V]]:
    """Analisis hacia delante de lo que vale por TODOS los caminos (la interseccion).

    El estado es `{registro: valor}` (una copia, una constante, el simbolo que contiene...). `step`
    lo actualiza para cada instruccion. Devuelve el estado a la entrada de cada bloque; un bloque
    al que no llega nada (codigo muerto) tiene el estado vacio. La entrada de la funcion
    empieza vacia, y un camino aun sin calcular no resta (se parte de 'todo vale')."""
    preds = predecessors(blocks)
    entry: list[dict[int, V] | None] = [None] * len(blocks)
    out: list[dict[int, V] | None] = [None] * len(blocks)
    entry[0] = {}
    changed = True
    while changed:
        changed = False
        for b, block in enumerate(blocks):
            if b != 0:
                known = [o for o in (out[p] for p in preds[b]) if o is not None]
                if not known:
                    continue
                new = {k: v for k, v in known[0].items() if all(o.get(k) == v for o in known[1:])}
                if entry[b] != new:
                    entry[b], changed = new, True
            state = dict(entry[b] or {})
            for line in block.lines:
                if line.kind == "instr":
                    step(state, line)
            if out[b] != state:
                out[b], changed = state, True
    return [e if e is not None else {} for e in entry]


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
    preds = predecessors(blocks)
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
    preds = predecessors(blocks)
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
