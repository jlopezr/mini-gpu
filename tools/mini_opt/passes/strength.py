"""Reduccion de fuerza de los accesos indexados de un bucle: un puntero que avanza en vez de recalcular la direccion

    ADD t, fila, x ; SHL t, t, 2 ; ADD t, t, base ; LOAD v, t, 0       (en cada vuelta, por cada acceso)
      ->  LOAD v, P, k                                                  (P avanza una vez por vuelta)

lcc compila `a[(y + 1) * 168 + 8 + x + k]` con la cuenta entera de cada acceso: cuatro instrucciones donde
a mano se escribe una `LOAD` con desplazamiento constante sobre un puntero que avanza. Para un bucle con una
variable de induccion `ADDI i, i, c` o `ADD i, i, s` (`s` invariante; la unica escritura de `i` en el bucle, en
un bloque que se ejecuta una vez por vuelta: domina al ultimo y no esta en un bucle anidado), cada
direccion que es una suma de registros invariantes del bucle, `i` y una constante, con `SHL` por una
constante, es afin en `i`:

    direccion = sum(coef_r * r) + coef_i * i + const        (en bytes)

Los accesos con los mismos registros y coeficientes (solo cambia `const`: las vecinas `x - 1`, `x`, `x + 1`)
comparten un puntero `P`, que el preheader deja en `sum(...) + coef_i * i0 + const_minimo` y que el bloque
de la actualizacion avanza `coef_i * c`. Cada acceso pasa a `LOAD v, P, const - const_minimo`; las cuentas
que se quedan sin uso las borra el DCE.

Un acceso ve `i` antes o despues de su paso: en el mismo bloque se ve por el orden; en otro, despues si el bloque
del paso lo domina, y antes si no se llega a el desde el paso sin volver a la cabecera (si no es ninguna de las
dos, no se toca). `d[idx] = *(s++); idx += width;` (el `wipe_doMelt` de Doom) tiene asi dos variables de
induccion en el cuerpo, y la del contador del `for` en el ultimo bloque.

Una variable de induccion que tras el cambio solo se lee a si misma (su propio paso) y no sale viva del bucle se
borra (`drop_dead_ivs`): el DCE no la ve muerta, porque su paso la lee en la vuelta siguiente.

Despues, si el bucle solo usa su contador para salir (`for (j = n; j; j--)`: `BNE j, R0` en la cabecera, `j` de uno
en uno y nada mas que lo lea), la salida pasa a comparar un puntero que avanza una constante (potencia de dos, no
cero) con su valor final, que el preheader calcula una vez (`fin = P + paso * j`), y el contador desaparece
(`replace_counter`).

Solo se toca un grupo si el bucle queda mas corto (con mas peso en lo que se ejecuta en cada vuelta);
hace falta un registro libre para `P` (y otro para el calculo del preheader). Las direcciones se evaluan dentro
de un bloque; un registro definido en otro bloque del bucle que no sea la variable de induccion no se sigue.
Un bucle con llamadas, o con mas de una arista de vuelta, no se toca."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace

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
    # registro -> su paso, la unica escritura en el ultimo bloque: una constante (`ADDI i, i, c`) o un
    # registro que el bucle no escribe (`ADD i, i, s`, escrito ("R", s))
    ivs: dict[int, int | tuple[str, int]]
    dom: list[set[int]]                     # dominadores de cada bloque
    ivblock: dict[int, int] = field(default_factory=dict)     # registro -> bloque de su paso
    reach: dict[int, set[int]] = field(default_factory=dict)  # bloques a los que se llega desde el paso sin volver a la cabecera


def reachable(blocks: list[Block], start: int, header: int, body: set[int]) -> set[int]:
    seen: set[int] = set()
    stack = [s for s in blocks[start].succ if s in body and s != header]
    while stack:
        b = stack.pop()
        if b not in seen:
            seen.add(b)
            stack.extend(s for s in blocks[b].succ if s in body and s != header)
    return seen


def analyze(blocks: list[Block], header: int, body: set[int], dom: list[set[int]],
            inner: set[int] = frozenset()) -> Loop | None:
    """`inner`: los bloques de los bucles anidados (alli una instruccion se ejecuta mas de una vez por vuelta)."""
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
    ivs: dict[int, int | tuple[str, int]] = {}
    ivblock: dict[int, int] = {}
    reach: dict[int, set[int]] = {}
    for b in sorted(body):
        if b not in dom[latch] or b in inner:               # no se ejecuta exactamente una vez por vuelta
            continue
        for line in blocks[b].lines:
            if line.kind != "instr" or len(line.args) != 3:
                continue
            r = reg_of(line.args[0])
            if not r or count[r] != 1:
                continue
            first, second = reg_of(line.args[1]), reg_of(line.args[2])
            if line.op == "ADDI" and r == first and number(line.args[2]):
                ivs[r] = number(line.args[2])
            elif line.op == "ADD" and r in (first, second):
                step = second if r == first else first
                if step and step != r and step not in written:  # el paso es otro registro que el bucle no escribe
                    ivs[r] = ("R", step)
            if r in ivs and r not in ivblock:
                ivblock[r] = b
                reach[r] = reachable(blocks, b, header, body)
    return Loop(header, body, pre.index, latch, written, ivs, dom, ivblock, reach)


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
            break
        for line in reversed(blocks[current].lines):
            if line.kind == "instr" and r in defs_uses(line)[0]:
                return number(line.args[1]) if line.op in ("MOVI", "LI") and len(line.args) == 2 else None
        current = preds[current][0] if len(preds[current]) == 1 else None
    # la unica definicion de la funcion, si domina al bucle (un `MOVI` que `licm` dejo en la entrada)
    found = [(i, line) for i, block in enumerate(blocks) for line in block.lines
             if line.kind == "instr" and r in defs_uses(line)[0]]
    if len(found) == 1 and found[0][0] in loop.dom[loop.pre]:
        line = found[0][1]
        return number(line.args[1]) if line.op in ("MOVI", "LI") and len(line.args) == 2 else None
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
    if r not in loop.ivs:
        return None
    # en el bloque del paso, por encima de el (si estuviera debajo, la definicion se habria visto arriba)
    where = loop.ivblock[r]
    if b == where or b not in loop.reach[r]:
        return {r: 1}, 0
    if where in loop.dom[b]:                                    # despues del paso
        step = loop.ivs[r]
        return ({r: 1}, step) if isinstance(step, int) else add(({r: 1}, 0), ({step[1]: 1}, 0))
    return None                                                 # a veces antes y a veces despues


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


def scaled(dest: int, r: int, c: int) -> list | None:
    """`dest = c * r`, con `c != 1`: sumas consigo misma si es potencia de dos, `MUL` si no."""
    if c > 1 and not c & (c - 1):
        return ([instr("ADD", f"R{dest}", f"R{r}", f"R{r}")]
                + [instr("ADD", f"R{dest}", f"R{dest}", f"R{dest}") for _ in range(c.bit_length() - 2)])
    if not -32768 <= c <= 32767:
        return None
    return [instr("MOVI", f"R{dest}", str(c)), instr("MUL", f"R{dest}", f"R{dest}", f"R{r}")]


def doubled(pointer: int, ratio: int) -> list:
    """`pointer *= ratio`, con `ratio` potencia de dos."""
    return [instr("ADD", f"R{pointer}", f"R{pointer}", f"R{pointer}") for _ in range(ratio.bit_length() - 1)]


def horner(key: tuple, const0: int, pointer: int) -> list | None:
    """El puntero sin registro de apoyo: se suman primero los registros con el mismo coeficiente y se va multiplicando
    de mayor a menor (`4 * (i + fila) + base`). Hace falta que los coeficientes sean potencias de dos."""
    iv, coef, others = key
    by_coef: dict[int, list[int]] = {}
    for r, c in [(iv, coef)] + list(others):
        by_coef.setdefault(c, []).append(r)
    coefs = sorted(by_coef)
    if coefs[0] <= 0 or any(c & (c - 1) for c in coefs):
        return None
    lines: list = []
    previous = None
    for c in reversed(coefs):
        if previous is not None:
            lines += doubled(pointer, previous // c)
        for r in by_coef[c]:
            lines.append(instr("ADD", f"R{pointer}", f"R{r}", "R0") if not lines
                         else instr("ADD", f"R{pointer}", f"R{pointer}", f"R{r}"))
        previous = c
    lines += doubled(pointer, coefs[0])
    if const0:
        if not -32768 <= const0 <= 32767:
            return None
        lines.append(instr("ADDI", f"R{pointer}", f"R{pointer}", str(const0)))
    return lines


def prelude(key: tuple, const0: int, pointer: int, scratch: int | None) -> list | None:
    """Las instrucciones del preheader que dejan en `pointer` la direccion del primer acceso."""
    simple = horner(key, const0, pointer)
    if simple is not None:
        return simple
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
        product = scaled(dest, r, c) if dest is not None else None
        if product is None:
            return None
        lines.extend(product)
        if not first:
            lines.append(instr("ADD", f"R{pointer}", f"R{pointer}", f"R{scratch}"))
        first = False
    if const0:
        if not -32768 <= const0 <= 32767:
            return None
        lines.append(instr("ADDI", f"R{pointer}", f"R{pointer}", str(const0)))
    return lines


OK, NEEDS_REGISTER, IMPOSSIBLE = 0, 1, 2
MAX_REPEATED_ADDS = 4                                   # sumar el paso varias veces en vez de gastar un registro


def apply(blocks: list[Block], loop: Loop, key: tuple, members: list, pointer: int, scratch: int | None,
          spare: int | None, steps: dict) -> int:
    """Deja el puntero en el preheader, reescribe los accesos y avanza el puntero en el ultimo bloque. `steps`
    guarda los registros que ya valen `coef * paso` (cuando el paso es un registro) para compartirlos; `spare`
    es un registro libre para uno nuevo, y sin el se suma el paso `coef` veces. Devuelve OK, NEEDS_REGISTER (con
    otro libre quiza saldria) o IMPOSSIBLE."""
    const0 = min(m[2] for m in members)
    lines = prelude(key, const0, pointer, scratch)
    if lines is None:
        return NEEDS_REGISTER if scratch is None else IMPOSSIBLE
    if any(not -32768 <= m[2] - const0 <= 32767 for m in members):
        return IMPOSSIBLE
    step = loop.ivs[key[0]]
    if isinstance(step, int):
        amount = key[1] * step
        if not -32768 <= amount <= 32767:
            return IMPOSSIBLE
        advance = [instr("ADDI", f"R{pointer}", f"R{pointer}", str(amount))]
    elif key[1] == 1:
        advance = [instr("ADD", f"R{pointer}", f"R{pointer}", f"R{step[1]}")]
    elif (step[1], key[1]) in steps:
        advance = [instr("ADD", f"R{pointer}", f"R{pointer}", f"R{steps[(step[1], key[1])]}")]
    elif spare is not None:
        product = scaled(spare, step[1], key[1])
        if product is None:
            return IMPOSSIBLE
        lines += product
        steps[(step[1], key[1])] = spare
        advance = [instr("ADD", f"R{pointer}", f"R{pointer}", f"R{spare}")]
    elif 1 < key[1] <= MAX_REPEATED_ADDS:
        advance = [instr("ADD", f"R{pointer}", f"R{pointer}", f"R{step[1]}") for _ in range(key[1])]
    else:
        return NEEDS_REGISTER
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
    latch.lines[at:at] = advance
    return OK


def drop_dead_ivs(blocks: list[Block], body: set[int], stats: dict | None = None) -> int:
    """Borra el paso (`ADDI i, i, c` / `ADD i, i, s`) de un registro que en el bucle solo lee ese paso y que no
    sale vivo por ninguna salida. Devuelve cuantos ha borrado."""
    live_in = live_in_blocks(blocks, liveness(blocks))
    exits = {s for b in body for s in blocks[b].succ if s not in body}
    touched: Counter = Counter()                    # registro -> lineas del bucle que lo leen o lo escriben
    for b in body:
        for line in blocks[b].lines:
            if line.kind == "instr":
                defs, uses = defs_uses(line)
                for r in defs | uses:
                    touched[r] += 1
    removed = 0
    for b in sorted(body):
        for line in list(blocks[b].lines):
            if line.kind != "instr" or line.op not in ("ADD", "ADDI") or len(line.args) != 3:
                continue
            r = reg_of(line.args[0])
            if not r or r not in (reg_of(line.args[1]), reg_of(line.args[2])) or touched[r] != 1:
                continue
            if any(r in live_in[s] for s in exits):
                continue
            blocks[b].lines.remove(line)
            removed += 1
    if stats is not None and removed:
        stats["strength.dead_ivs"] = stats.get("strength.dead_ivs", 0) + removed
    return removed


def replace_counter(blocks: list[Block], header: int, body: set[int], allowed: list[int], dom: list[set[int]],
                    inner: set[int], stats: dict) -> None:
    """`BNE j, R0, cuerpo` con `j` que solo cuenta vueltas -> `BNE P, fin, cuerpo`."""
    loop = analyze(blocks, header, body, dom, inner)
    if loop is None:
        return
    test = blocks[header].last_instr()
    if test is None or test.op != "BNE" or len(test.args) != 3:
        return
    a, b = reg_of(test.args[0]), reg_of(test.args[1])
    counter = a if b == 0 else b if a == 0 else None
    if not counter or loop.ivs.get(counter) not in (1, -1) or loop.ivblock[counter] == header:
        return
    uses: Counter = Counter()
    for block in body:
        for line in blocks[block].lines:
            if line.kind == "instr":
                defs, used = defs_uses(line)
                for r in defs | used:
                    uses[r] += 1
    if uses[counter] != 2:                          # su paso y el salto
        return
    exits = {s for block in body for s in blocks[block].succ if s not in body}
    live_in = live_in_blocks(blocks, liveness(blocks))
    if any(counter in live_in[s] for s in exits):
        return
    pointer = None
    for r, step in sorted(loop.ivs.items()):
        if (r != counter and isinstance(step, int) and step and not step & (abs(step) - 1)
                and loop.ivblock[r] != header and abs(step) <= 1 << MAX_SHIFT):
            pointer = r, step
            break
    if pointer is None:
        return
    free = free_registers(blocks, body, header, allowed, live_in)
    if not free:
        return
    end = free[0]
    r, step = pointer
    # la vuelta k empieza con j = j0 + c*k y P = P0 + step*k; se sale con j == 0, o sea en k = -j0/c
    shift = abs(step).bit_length() - 1
    forwards = (step > 0) == (loop.ivs[counter] < 0)    # fin = P + |step|*j0 si avanzan en sentido contrario
    lines = ([instr("SHLI", f"R{end}", f"R{counter}", str(shift))] if shift
             else [instr("ADD", f"R{end}", f"R{counter}", "R0")])
    lines.append(instr("ADD", f"R{end}", f"R{r}", f"R{end}") if forwards
                 else instr("SUB", f"R{end}", f"R{r}", f"R{end}"))
    for line in lines:
        insert_in_preheader(blocks[loop.pre], line)
    test.args[0], test.args[1] = f"R{r}", f"R{end}"
    drop_dead_ivs(blocks, body, stats)
    stats["strength.counters"] = stats.get("strength.counters", 0) + 1


def weight(blocks: list[Block], loop: Loop, dom_latch: set[int]) -> int:
    """Instrucciones del bucle, el doble las de los bloques que se ejecutan en cada vuelta."""
    return sum((2 if b in dom_latch else 1) * sum(1 for l in blocks[b].lines if l.kind == "instr")
               for b in loop.body)


def trial_copy(blocks: list[Block], members: list) -> list[Block]:
    """Una copia de `blocks` para probar `apply`: listas de lineas nuevas, y copia solo de los accesos que cambia
    (las demas lineas se comparten: `apply` y `remove_dead` las insertan o quitan, no las modifican)."""
    trial = [Block(block.index, list(block.lines), block.succ) for block in blocks]
    for b, position, _ in members:
        line = trial[b].lines[position]
        trial[b].lines[position] = replace(line, args=list(line.args))
    return trial


def reduce_loop(blocks: list[Block], header: int, body: set[int], allowed: list[int], dom: list[set[int]],
                stats: dict, inner: set[int] = frozenset()) -> None:
    """`dom` vale para todo el pase: solo se insertan y borran instrucciones, el grafo no cambia."""
    created: set[int] = set()
    rejected: set = set()
    steps: dict[tuple[int, int], int] = {}                  # (registro del paso, coeficiente) -> registro con el producto
    while True:
        loop = analyze(blocks, header, body, dom, inner)
        if loop is None or not loop.ivs:
            return
        groups = collect(blocks, loop, created)
        live_in = live_in_blocks(blocks, liveness(blocks))
        free = free_registers(blocks, body, header, allowed, live_in)
        if not free:
            return
        dom_latch = dom[loop.latch] & body
        chosen = None
        for key in sorted((k for k in groups if k not in rejected), key=lambda k: (-len(groups[k]), k)):
            trial = trial_copy(blocks, groups[key])
            scratch = free[1] if len(free) > 1 else None
            spare = free[2] if len(free) > 2 else None
            outcome = apply(trial, loop, key, groups[key], free[0], scratch, spare, dict(steps))
            if outcome != OK:
                if outcome == IMPOSSIBLE:
                    rejected.add(key)
                continue
            remove_dead(trial, {}, "strength")
            if drop_dead_ivs(trial, body):
                remove_dead(trial, {}, "strength")
            if weight(trial, loop, dom_latch) < weight(blocks, loop, dom_latch):
                chosen = (key, free[0], scratch, spare)
                break
            rejected.add(key)
        if chosen is None:
            return
        key, pointer, scratch, spare = chosen
        apply(blocks, loop, key, groups[key], pointer, scratch, spare, steps)
        remove_dead(blocks, stats, "strength")
        if drop_dead_ivs(blocks, body, stats):
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
        before = stats.get("strength.pointers", 0) + stats.get("strength.counters", 0)
        kernel = function.name.startswith(KERNEL_PREFIX)
        allowed = list(range(5, 16)) + [1, 2, 3, 4, 31] + (list(range(16, 30)) if kernel else [])
        dom = dominators(blocks)
        loops = natural_loops(blocks, dom)
        for header, body in sorted(loops.items(), key=lambda item: (len(item[1]), item[0])):
            inner = {b for other, nested in loops.items() if other != header and other in body for b in nested}
            reduce_loop(blocks, header, body, allowed, dom, stats, inner)
            replace_counter(blocks, header, body, allowed, dom, inner, stats)
        if stats.get("strength.pointers", 0) + stats.get("strength.counters", 0) > before:
            stats["strength.functions"] = stats.get("strength.functions", 0) + 1
            function.body = [line for block in blocks for line in block.lines]
