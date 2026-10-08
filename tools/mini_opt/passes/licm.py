"""Sacar de un bucle lo que no cambia en el (LICM, loop-invariant code motion)

lcc no hace nada entre bloques: la constante de una comparacion, el `MOVI` previo a cada
desplazamiento (la GPU no tiene SHLI) o una cuenta con valores fijos se repiten en cada
vuelta. Para cada bucle sin bucles dentro y sin llamadas, una instruccion pura cuyos operandos
no se escriben en el bucle (una constante, `SHL t, a, c` con `a` y `c` fijos...) se calcula
una vez en el preheader, en un registro que el bucle no usa, y se borra de dentro. Cada uso
tiene que venir solo de esa definicion (definiciones que alcanzan), y el registro no puede
estar vivo al salir del bucle por otra via. No toca cargas (haria falta saber que nada las
modifica) ni lo que puede dar un fallo (DIV, REM). Un cero se sustituye por R0 sin gastar
registro. Los registros libres son R5..R15, R1..R4 y R31 (si la vida de registros dice que lo estan); en un kernel, tambien los R16..R29 que nadie usa."""
from __future__ import annotations

from ..flow import Block, build_cfg, dominators, live_in_blocks, liveness, natural_loops
from ..isa import PURE_OPS, REGISTER_RE, defs_uses, instr, number, reg_of, use_slots
from ..model import Line, Unit
from .kernels import KERNEL_PREFIX
from ..registry import register_pass


ENTRY = frozenset({0})                      # "la definicion de fuera del bucle"


def reaching_in_loop(blocks: list[Block], body: set[int]):
    """Definiciones que alcanzan cada uso dentro del bucle.

    Devuelve (uses_of, reach, out): `uses_of[id(def)]` = lista de (linea, registro) que esa
    definicion alcanza; `reach[(id(linea), registro)]` = conjunto de definiciones que llegan a ese
    uso (ENTRY = la de antes del bucle); `out[bloque]` = el estado al salir del bloque."""
    preds: dict[int, list[int]] = {b: [] for b in body}
    for b in body:
        for s in blocks[b].succ:
            if s in body:
                preds[s].append(b)
    out: dict[int, dict[int, frozenset]] = {b: {} for b in body}

    def entering(b: int) -> dict[int, frozenset]:
        states = [out[p] for p in preds[b]]
        outside = [p for p in range(len(blocks)) if b in blocks[p].succ and p not in body]
        states += [{}] * len(outside)              # desde fuera: todo viene de ENTRY
        keys = set().union(*(s.keys() for s in states)) if states else set()
        return {k: frozenset().union(*(s.get(k, ENTRY) for s in states)) for k in keys}

    def run(state: dict, block: Block) -> dict:
        for line in block.lines:
            if line.kind == "instr":
                for reg in defs_uses(line)[0]:
                    state[reg] = frozenset({id(line)})
        return state

    changed = True
    while changed:
        changed = False
        for b in sorted(body):
            new = run(dict(entering(b)), blocks[b])
            if new != out[b]:
                out[b], changed = new, True
    uses_of: dict[int, list] = {}
    reach: dict[tuple[int, int], frozenset] = {}
    for b in sorted(body):
        state = dict(entering(b))
        for line in blocks[b].lines:
            if line.kind != "instr":
                continue
            defs, uses = defs_uses(line)
            for reg in uses:
                found = state.get(reg, ENTRY)
                reach[(id(line), reg)] = found
                for d in found:
                    if d:
                        uses_of.setdefault(d, []).append((line, reg))
            for reg in defs:
                state[reg] = frozenset({id(line)})
    return uses_of, reach, out


def licm_loop(blocks: list[Block], body: set[int], header: int, pre: Block, allowed: list[int],
               stats: dict) -> None:
    """Saca lo invariante de un bucle hasta que no quede nada que sacar o registros."""
    while True:
        live_in = live_in_blocks(blocks, liveness(blocks))
        uses_of, reach, out = reaching_in_loop(blocks, body)
        written: set[int] = set()
        mentioned: set[int] = set()
        for b in body:
            for line in blocks[b].lines:
                if line.kind == "instr":
                    defs, uses = defs_uses(line)
                    written |= defs
                    mentioned |= defs | uses
        free = [r for r in allowed if r not in mentioned and r not in live_in[header]]
        groups: dict[tuple, list[tuple[Block, Line]]] = {}
        for b in sorted(body):
            for line in blocks[b].lines:
                if line.kind != "instr" or line.op not in PURE_OPS:
                    continue
                defs, uses = defs_uses(line)
                if len(defs) != 1 or uses & written:
                    continue
                t = next(iter(defs))
                reached = uses_of.get(id(line), [])
                if not reached:
                    continue
                if any(reach[(id(u), r)] != frozenset({id(line)}) or use_slots(u) is None
                       or not any(reg_of(u.args[i]) == t for i in use_slots(u)) for u, r in reached):
                    continue
                if any(t in live_in[s] and id(line) in out[x].get(t, ())
                       for x in body for s in blocks[x].succ if s not in body):
                    continue
                groups.setdefault((line.op, tuple(a.upper() if REGISTER_RE.match(a.strip()) else a
                                                    for a in line.args[1:])), []).append((blocks[b], line))
        if not groups:
            return
        # los ceros no gastan registro; despues, lo que mas veces se repite
        zero = [k for k in groups if k[0] in ("MOVI", "LI") and number(k[1][0]) == 0]
        ordered = zero + sorted((k for k in groups if k not in zero), key=lambda k: -len(groups[k]))
        key = None
        for k in ordered:
            if k in zero or free:
                key = k
                break
        if key is None:
            return
        if key in zero:
            name = "R0"
            stats["licm.zeros"] = stats.get("licm.zeros", 0) + 1
        else:
            name = f"R{free[0]}"
            stats["licm.registers"] = stats.get("licm.registers", 0) + 1
            op, args = key
            template = groups[key][0][1]
            at = len(pre.lines)
            if pre.lines and pre.lines[-1].kind == "instr" and pre.lines[-1].op == "BRA":
                at -= 1
            pre.lines.insert(at, instr(op, name, *template.args[1:]))
        for block, line in groups[key]:
            t = reg_of(line.args[0])
            for use, _ in uses_of[id(line)]:
                for i in use_slots(use):
                    if reg_of(use.args[i]) == t:
                        use.args[i] = name
            block.lines = [l for l in block.lines if l is not line]
            stats["licm.removed"] = stats.get("licm.removed", 0) + 1


@register_pass("licm", "saca de los bucles lo que no cambia en ellos (constantes y cuentas con valores fijos)")
def pass_licm(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        blocks = build_cfg(function)
        if len(blocks) < 2:
            continue
        dom = dominators(blocks)
        loops = natural_loops(blocks, dom)
        kernel = function.name.startswith(KERNEL_PREFIX)
        # primero los temporales, luego los de argumentos y el enlace (la vida de registros dice cuando
        # estan libres: R1/R2 al retornar, R31 hasta su `JR`), y en un kernel los preservados sin uso
        allowed = list(range(5, 16)) + [1, 2, 3, 4, 31] + (list(range(16, 30)) if kernel else [])
        for header, body in sorted(loops.items()):
            if any(h != header and h in body for h in loops):         # tiene un bucle dentro
                continue
            if any(l.kind == "instr" and l.op in ("JAL", "JALR") for b in body for l in blocks[b].lines):
                continue
            outside = [b.index for b in blocks if header in b.succ and b.index not in body]
            if len(outside) != 1 or blocks[outside[0]].succ != [header]:
                continue
            pre = blocks[outside[0]]
            before = stats.get("licm.removed", 0)
            licm_loop(blocks, body, header, pre, allowed, stats)
            if stats.get("licm.removed", 0) > before:
                stats["licm.loops"] = stats.get("licm.loops", 0) + 1
        function.body = [line for block in blocks for line in block.lines]
