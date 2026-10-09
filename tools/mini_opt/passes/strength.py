"""Reduccion de fuerza de los accesos indexados de un bucle: un puntero que avanza en vez de recalcular la direccion

    ADD t, fila, x ; SHL t, t, 2 ; ADD t, t, base ; LOAD v, t, 0       (en cada vuelta, por cada acceso)
      ->  LOAD v, P, k                                                  (P avanza una vez por vuelta)

lcc compila `a[(y + 1) * 168 + 8 + x + k]` con la cuenta entera de cada acceso: cuatro instrucciones donde
a mano se escribe una `LOAD` con desplazamiento constante sobre un puntero que avanza. Para un bucle con una
variable de induccion `ADDI i, i, c` (la unica escritura de `i` en el bucle, en el ultimo bloque), cada
direccion que es una suma de registros invariantes del bucle, `i` y una constante, con `SHL` por una
constante, es afin en `i`:

    direccion = sum(coef_r * r) + coef_i * i + const        (en bytes)

Los accesos con los mismos registros y coeficientes (solo cambia `const`: las vecinas `x - 1`, `x`, `x + 1`)
comparten un puntero `P`, que el preheader deja en `sum(...) + coef_i * i0 + const_minimo` y que el bloque
de la actualizacion avanza `coef_i * c`. Cada acceso pasa a `LOAD v, P, const - const_minimo`; las cuentas
que se quedan sin uso las borra el DCE.

Solo se toca un grupo si el bucle queda mas corto (con mas peso en lo que se ejecuta en cada vuelta);
hace falta un registro libre para `P` (y otro para el calculo del preheader). Las direcciones se evaluan dentro
de un bloque; un registro definido en otro bloque del bucle que no sea la variable de induccion no se sigue.
Un bucle con llamadas, o con mas de una arista de vuelta, no se toca."""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass

from ..dead import remove_dead
from ..flow import Block, build_cfg, dominators, live_in_blocks, liveness, natural_loops, predecessors
from ..isa import BRANCHES, LOADS, STORES, defs_uses, instr, number, reg_of
from ..model import Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX
from .licm import free_registers, insert_in_preheader, preheader

MEMORY = LOADS | STORES
Affine = tuple[dict[int, int], int]         # ({registro: coeficiente}, constante), en bytes
MAX_SHIFT = 5


@dataclass
class Loop:
    header: int
    body: set[int]
    pre: int
    latch: int
    written: set[int]
    ivs: dict[int, int]                     # registro -> paso de su ADDI, la unica escritura en el ultimo bloque


def analyze(blocks: list[Block], header: int, body: set[int]) -> Loop | None:
    pre = preheader(blocks, header, body)
    latches = [b for b in body if header in blocks[b].succ]
    if pre is None or len(latches) != 1:
        return None
    latch = latches[0]
    if [s for s in blocks[latch].succ if s in body] != [header]:
        return None
    written: set[int] = set()
    count: Counter = Counter()
    for b in body:
        for line in blocks[b].lines:
            if line.kind != "instr":
                continue
            if line.op in ("JAL", "JALR"):
                return None
            for r in defs_uses(line)[0]:
                written.add(r)
                count[r] += 1
    ivs: dict[int, int] = {}
    for line in blocks[latch].lines:
        if line.kind == "instr" and line.op == "ADDI" and len(line.args) == 3:
            r = reg_of(line.args[0])
            step = number(line.args[2])
            if r and r == reg_of(line.args[1]) and count[r] == 1 and step:
                ivs[r] = step
    return Loop(header, body, pre.index, latch, written, ivs)


def constant(blocks: list[Block], loop: Loop, b: int, j: int, r: int) -> int | None:
    """El valor de `r` si es una constante `MOVI` (en el bloque antes de `j`, o en el preheader y lo que lo precede)."""
    if r == 0:
        return 0
    for line in reversed(blocks[b].lines[:j]):
        if line.kind == "instr" and r in defs_uses(line)[0]:
            return number(line.args[1]) if line.op in ("MOVI", "LI") and len(line.args) == 2 else None
    if r in loop.written:
        return None
    preds = predecessors(blocks)
    current: int | None = loop.pre
    for _ in range(6):
        if current is None:
            return None
        for line in reversed(blocks[current].lines):
            if line.kind == "instr" and r in defs_uses(line)[0]:
                return number(line.args[1]) if line.op in ("MOVI", "LI") and len(line.args) == 2 else None
        current = preds[current][0] if len(preds[current]) == 1 else None
    return None


def add(a: Affine | None, b: Affine | None, sign: int = 1) -> Affine | None:
    if a is None or b is None:
        return None
    terms = dict(a[0])
    for r, c in b[0].items():
        terms[r] = terms.get(r, 0) + sign * c
        if terms[r] == 0:
            del terms[r]
    return terms, a[1] + sign * b[1]


def affine(blocks: list[Block], loop: Loop, b: int, position: int, r: int, depth: int = 0) -> Affine | None:
    """`r` justo antes de `blocks[b].lines[position]`, como suma de invariantes, variable de induccion y constante."""
    if r == 0:
        return {}, 0
    if depth > 12:
        return None
    for j in range(position - 1, -1, -1):
        line = blocks[b].lines[j]
        if line.kind != "instr" or r not in defs_uses(line)[0]:
            continue
        args = line.args
        if line.op == "ADD" and len(args) == 3:
            return add(affine(blocks, loop, b, j, reg_of(args[1]) or 0, depth + 1),
                       affine(blocks, loop, b, j, reg_of(args[2]) or 0, depth + 1))
        if line.op == "ADDI" and len(args) == 3 and number(args[2]) is not None:
            base = affine(blocks, loop, b, j, reg_of(args[1]) or 0, depth + 1)
            return None if base is None else (base[0], base[1] + number(args[2]))
        if line.op == "SUB" and len(args) == 3:
            return add(affine(blocks, loop, b, j, reg_of(args[1]) or 0, depth + 1),
                       affine(blocks, loop, b, j, reg_of(args[2]) or 0, depth + 1), -1)
        if line.op == "MUL" and len(args) == 3:
            left = affine(blocks, loop, b, j, reg_of(args[1]) or 0, depth + 1)
            right = affine(blocks, loop, b, j, reg_of(args[2]) or 0, depth + 1)
            if left is None or right is None:
                return None
            if not left[0]:
                left, right = right, left                   # la constante, a la derecha
            if right[0]:
                return None                                 # producto de dos variables
            k = right[1]
            return {r: c * k for r, c in left[0].items() if c * k}, left[1] * k
        if line.op in ("SHL", "SHLI") and len(args) == 3:
            shift = (constant(blocks, loop, b, j, reg_of(args[2])) if line.op == "SHL" else number(args[2]))
            base = affine(blocks, loop, b, j, reg_of(args[1]) or 0, depth + 1)
            if base is None or shift is None or not 0 <= shift <= MAX_SHIFT:
                return None
            return {k: v << shift for k, v in base[0].items()}, base[1] << shift
        if line.op in ("MOVI", "LI") and len(args) == 2 and number(args[1]) is not None:
            return {}, number(args[1])
        return None
    if r not in loop.written:
        return {r: 1}, 0
    return ({r: 1}, 0) if r in loop.ivs else None             # antes de su ADDI: despues, la definicion se ve arriba


def collect(blocks: list[Block], loop: Loop, created: set[int]) -> dict[tuple, list[tuple[int, int, int]]]:
    """Los accesos afines en una variable de induccion, agrupados por registros y coeficientes."""
    groups: dict[tuple, list[tuple[int, int, int]]] = {}
    for b in sorted(loop.body):
        for position, line in enumerate(blocks[b].lines):
            if line.kind != "instr" or line.op not in MEMORY or len(line.args) != 3:
                continue
            base, offset = reg_of(line.args[1]), number(line.args[2])
            if not base or offset is None:
                continue
            found = affine(blocks, loop, b, position, base)
            if found is None:
                continue
            terms, const = found
            ivs = [r for r in terms if r in loop.ivs and r not in created]
            if len(ivs) != 1 or any(r in loop.ivs and r != ivs[0] for r in terms):
                continue
            key = (ivs[0], terms[ivs[0]], tuple(sorted((r, c) for r, c in terms.items() if r != ivs[0])))
            groups.setdefault(key, []).append((b, position, const + offset))
    return groups


def prelude(key: tuple, const0: int, pointer: int, scratch: int | None) -> list | None:
    """Las instrucciones del preheader que dejan en `pointer` la direccion del primer acceso."""
    iv, coef, others = key
    lines = []
    first = True
    for r, c in [(iv, coef)] + list(others):
        dest = pointer if first else scratch
        if c == 1:
            lines.append(instr("ADD", f"R{pointer}", f"R{r}", "R0") if first
                         else instr("ADD", f"R{pointer}", f"R{pointer}", f"R{r}"))
            first = False
            continue
        if dest is None:
            return None
        if c > 1 and not c & (c - 1):                           # potencia de dos: sumas consigo misma
            lines.append(instr("ADD", f"R{dest}", f"R{r}", f"R{r}"))
            lines.extend(instr("ADD", f"R{dest}", f"R{dest}", f"R{dest}") for _ in range(c.bit_length() - 2))
        else:
            if not -32768 <= c <= 32767:
                return None
            lines.append(instr("MOVI", f"R{dest}", str(c)))
            lines.append(instr("MUL", f"R{dest}", f"R{dest}", f"R{r}"))
        if not first:
            lines.append(instr("ADD", f"R{pointer}", f"R{pointer}", f"R{scratch}"))
        first = False
    if const0:
        if not -32768 <= const0 <= 32767:
            return None
        lines.append(instr("ADDI", f"R{pointer}", f"R{pointer}", str(const0)))
    return lines


def apply(blocks: list[Block], loop: Loop, key: tuple, members: list, pointer: int, scratch: int | None) -> bool:
    const0 = min(m[2] for m in members)
    step = key[1] * loop.ivs[key[0]]
    lines = prelude(key, const0, pointer, scratch)
    if lines is None or not -32768 <= step <= 32767:
        return False
    if any(not -32768 <= m[2] - const0 <= 32767 for m in members):
        return False
    for b, position, const in members:
        access = blocks[b].lines[position]
        access.args[1], access.args[2] = f"R{pointer}", str(const - const0)
    for line in lines:
        insert_in_preheader(blocks[loop.pre], line)
    latch = blocks[loop.latch]
    at = len(latch.lines)
    for index in range(len(latch.lines) - 1, -1, -1):
        last = latch.lines[index]
        if last.kind == "instr":
            if last.op in BRANCHES or last.op in ("BRA", "JR"):
                at = index
            break
    latch.lines.insert(at, instr("ADDI", f"R{pointer}", f"R{pointer}", str(step)))
    return True


def weight(blocks: list[Block], loop: Loop, dom_latch: set[int]) -> int:
    """Instrucciones del bucle, el doble las de los bloques que se ejecutan en cada vuelta."""
    return sum((2 if b in dom_latch else 1) * sum(1 for l in blocks[b].lines if l.kind == "instr")
               for b in loop.body)


def reduce_loop(blocks: list[Block], header: int, body: set[int], allowed: list[int], stats: dict) -> None:
    created: set[int] = set()
    rejected: set = set()
    while True:
        loop = analyze(blocks, header, body)
        if loop is None or not loop.ivs:
            return
        groups = collect(blocks, loop, created)
        live_in = live_in_blocks(blocks, liveness(blocks))
        free = free_registers(blocks, body, header, allowed, live_in)
        if not free:
            return
        dom_latch = dominators(blocks)[loop.latch] & body
        chosen = None
        for key in sorted((k for k in groups if k not in rejected), key=lambda k: (-len(groups[k]), k)):
            trial = copy.deepcopy(blocks)
            scratch = free[1] if len(free) > 1 else None
            if not apply(trial, loop, key, groups[key], free[0], scratch):
                rejected.add(key)
                continue
            remove_dead(trial, {}, "strength")
            if weight(trial, loop, dom_latch) < weight(blocks, loop, dom_latch):
                chosen = (key, free[0], scratch)
                break
            rejected.add(key)
        if chosen is None:
            return
        key, pointer, scratch = chosen
        apply(blocks, loop, key, groups[key], pointer, scratch)
        remove_dead(blocks, stats, "strength")
        created.add(pointer)
        stats["strength.pointers"] = stats.get("strength.pointers", 0) + 1


@register_pass("strength", "reduccion de fuerza: un puntero que avanza en vez de recalcular el indice de cada acceso")
def pass_strength(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if len(blocks) < 2:
            continue
        before = stats.get("strength.pointers", 0)
        kernel = function.name.startswith(KERNEL_PREFIX)
        allowed = list(range(5, 16)) + [1, 2, 3, 4, 31] + (list(range(16, 30)) if kernel else [])
        loops = natural_loops(blocks, dominators(blocks))
        for header, body in sorted(loops.items(), key=lambda item: (len(item[1]), item[0])):
            reduce_loop(blocks, header, body, allowed, stats)
        if stats.get("strength.pointers", 0) > before:
            stats["strength.functions"] = stats.get("strength.functions", 0) + 1
            function.body = [line for block in blocks for line in block.lines]
