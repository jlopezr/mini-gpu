"""LICM (loop-invariant code motion): sacar de un bucle lo que no cambia en el

lcc no hace nada entre bloques: la constante de una comparacion, el `MOVI` previo a cada
desplazamiento (la GPU no tiene SHLI) o una cuenta con valores fijos se repiten en cada
vuelta. Para cada bucle sin bucles dentro y sin llamadas, una instruccion pura cuyos operandos
no se escriben en el bucle (una constante, `SHL t, a, c` con `a` y `c` fijos...) se calcula
una vez en el preheader, en un registro que el bucle no usa, y se borra de dentro. Cada uso
tiene que venir solo de esa definicion (definiciones que alcanzan), y el registro no puede
estar vivo al salir del bucle por otra via. No toca cargas (haria falta saber que nada las
modifica) ni lo que puede dar un fallo (DIV, REM). Un cero se sustituye por R0 sin gastar
registro.

Los registros libres son R5..R15, R1..R4 y R31 (si la vida de registros dice que lo estan); en
un kernel, tambien los R16..R29 que nadie usa."""
from __future__ import annotations

from dataclasses import dataclass

from ..flow import (
    Block,
    build_cfg,
    dominators,
    live_in_blocks,
    liveness,
    natural_loops,
    predecessors,
)
from ..isa import (
    PURE_OPS,
    REGISTER_RE,
    defs_uses,
    instr,
    number,
    reg,
    reg_of,
    use_slots,
)
from ..isa import LOADS
from ..model import Line, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX
from .sharebase import split_address

ENTRY = frozenset({0})                      # "la definicion de fuera del bucle"

# `--assume-noalias`: en un kernel, lo que se escribe por un puntero que llega por los argumentos no pisa lo que el
# propio kernel lee por el nombre de una variable global. No se puede demostrar desde el ensamblador, asi que no
# es el comportamiento por defecto (ver `readonly_symbols`).
NOALIAS = False

Key = tuple[str, tuple[str, ...]]           # (mnemonico, operandos tras el destino): lo que se calcula
Candidate = tuple[Block, Line]


@dataclass
class Reaching:
    """Definiciones que alcanzan cada uso dentro de un bucle."""
    uses_of: dict[int, list[tuple[Line, int]]]      # id(def) -> (linea, registro) que esa def alcanza
    reach: dict[tuple[int, int], frozenset]         # (id(linea), registro) -> defs que llegan a ese uso
    out: dict[int, dict[int, frozenset]]            # bloque -> estado al salir


def reaching_in_loop(blocks: list[Block], body: set[int]) -> Reaching:
    """Definiciones que alcanzan cada uso dentro del bucle (ENTRY = la de antes del bucle)."""
    preds = predecessors(blocks)
    # None = aun sin calcular: no aporta nada. Empezar con {} (todo ENTRY) dejaria una ENTRY falsa atrapada en
    # cada ciclo cuando la definicion esta dentro del bucle (un bucle interior dentro del exterior).
    out: dict[int, dict[int, frozenset] | None] = {b: None for b in body}

    def entering(b: int) -> dict[int, frozenset]:
        states = [out[p] for p in preds[b] if p in body and out[p] is not None]
        states += [{} for p in preds[b] if p not in body]       # desde fuera: todo viene de ENTRY
        keys = set().union(*(s.keys() for s in states)) if states else set()
        return {k: frozenset().union(*(s.get(k, ENTRY) for s in states)) for k in keys}

    def run(state: dict[int, frozenset], block: Block) -> dict[int, frozenset]:
        for line in block.lines:
            if line.kind == "instr":
                for written in defs_uses(line)[0]:
                    state[written] = frozenset({id(line)})
        return state

    def ready(b: int) -> bool:
        return any(p not in body or out[p] is not None for p in preds[b])

    changed = True
    while changed:
        changed = False
        for b in sorted(body):
            if not ready(b):
                continue
            new = run(dict(entering(b)), blocks[b])
            if new != out[b]:
                out[b], changed = new, True
    for b in body:
        if out[b] is None:
            out[b] = {}                     # no lo alcanza ningun camino desde fuera del bucle
    uses_of: dict[int, list[tuple[Line, int]]] = {}
    reach: dict[tuple[int, int], frozenset] = {}
    for b in sorted(body):
        state = dict(entering(b))
        for line in blocks[b].lines:
            if line.kind != "instr":
                continue
            defs, uses = defs_uses(line)
            for used in uses:
                found = state.get(used, ENTRY)
                reach[(id(line), used)] = found
                for definition in found:
                    if definition:
                        uses_of.setdefault(definition, []).append((line, used))
            for written in defs:
                state[written] = frozenset({id(line)})
    return Reaching(uses_of, reach, out)


def can_move(line: Line, t: int, facts: Reaching, body: set[int], blocks: list[Block],
             live_in: list[set[int]]) -> bool:
    """Todo uso que alcanza `line` viene solo de ella, se sabe reescribir, y `t` no sale vivo del bucle
    con esta definicion."""
    reached = facts.uses_of.get(id(line), [])
    if not reached:
        return False
    for use, used in reached:
        slots = use_slots(use)
        if (facts.reach[(id(use), used)] != frozenset({id(line)}) or slots is None
                or not any(reg_of(use.args[i]) == t for i in slots)):
            return False
    for x in body:
        for s in blocks[x].succ:
            if s not in body and t in live_in[s] and id(line) in facts.out[x].get(t, ()):
                return False
    return True


def uses_of_definition(blocks: list[Block], block: int, start: int, register: int) -> list[Line]:
    """Las instrucciones que leen `register` tal como lo deja la que esta en `blocks[block].lines[start - 1]`,
    por cualquier camino y hasta que se reescriba."""
    found: list[Line] = []
    seen: set[int] = set()
    stack = [(block, start)]
    while stack:
        index, position = stack.pop()
        killed = False
        for line in blocks[index].lines[position:]:
            if line.kind != "instr":
                continue
            defs, uses = defs_uses(line)
            if register in uses:
                found.append(line)
            if register in defs:
                killed = True
                break
        if not killed:
            for s in blocks[index].succ:
                if s not in seen:
                    seen.add(s)
                    stack.append((s, 0))
    return found


def readonly_symbols(blocks: list[Block]) -> set[str]:
    """Simbolos que esta funcion solo lee: cada `LI Rx, simbolo+K` tiene como unicos usos `LOAD d, Rx, k`
    (ni una suma, ni un `STORE`, ni pasarlo a una llamada), por cualquier camino. No dice nada de lo que
    escribe otro codigo: la CPU puede escribir en el mientras el kernel no corre."""
    seen: set[str] = set()
    bad: set[str] = set()
    for b, block in enumerate(blocks):
        for position, line in enumerate(block.lines):
            if line.kind != "instr" or line.op != "LI" or len(line.args) != 2:
                continue
            address, register = split_address(line.args[1]), reg_of(line.args[0])
            if address is None or not register:
                continue
            seen.add(address[0])
            for use in uses_of_definition(blocks, b, position + 1, register):
                if not (use.op in LOADS and len(use.args) == 3 and reg_of(use.args[1]) == register):
                    bad.add(address[0])
    return seen - bad


def invariant_load_ok(line: Line, pre: Block, readonly: set[str]) -> bool:
    """Una carga cuya base es la direccion de un simbolo que el kernel solo lee (la ultima definicion de la base en
    el preheader es `LI base, simbolo+K`) es invariante mientras la base no cambie en el bucle."""
    if line.op not in LOADS or len(line.args) != 3:
        return False
    base = reg_of(line.args[1])
    for previous in reversed(pre.lines):
        if previous.kind == "instr" and base in defs_uses(previous)[0]:
            address = split_address(previous.args[1]) if previous.op == "LI" and len(previous.args) == 2 else None
            return address is not None and address[0] in readonly
    return False


def invariant_groups(blocks: list[Block], body: set[int], facts: Reaching,
                     live_in: list[set[int]], loads_ok=None) -> dict[Key, list[Candidate]]:
    """Las instrucciones que se pueden sacar, agrupadas por lo que calculan (una por grupo en el preheader)."""
    written: set[int] = set()
    for b in body:
        for line in blocks[b].lines:
            if line.kind == "instr":
                written |= defs_uses(line)[0]
    groups: dict[Key, list[Candidate]] = {}
    for b in sorted(body):
        for line in blocks[b].lines:
            if line.kind != "instr" or (line.op not in PURE_OPS and not (loads_ok and loads_ok(line))):
                continue
            defs, uses = defs_uses(line)
            if len(defs) != 1 or uses & written:
                continue
            if not can_move(line, next(iter(defs)), facts, body, blocks, live_in):
                continue
            operands = tuple(a.upper() if REGISTER_RE.match(a.strip()) else a for a in line.args[1:])
            groups.setdefault((line.op, operands), []).append((blocks[b], line))
    return groups


def free_registers(blocks: list[Block], body: set[int], header: int, allowed: list[int],
                   live_in: list[set[int]]) -> list[int]:
    """Registros de `allowed` que el bucle no toca y que no llegan vivos a el."""
    mentioned: set[int] = set()
    for b in body:
        for line in blocks[b].lines:
            if line.kind == "instr":
                mentioned |= set().union(*defs_uses(line))
    return [r for r in allowed if r not in mentioned and r not in live_in[header]]


def is_zero(key: Key) -> bool:
    return key[0] in ("MOVI", "LI") and number(key[1][0]) == 0


def choose_group(groups: dict[Key, list[Candidate]], free: list[int]) -> Key | None:
    """Los ceros no gastan registro; despues, lo que mas veces se repite (si queda registro)."""
    zeros = [k for k in groups if is_zero(k)]
    rest = sorted((k for k in groups if not is_zero(k)), key=lambda k: -len(groups[k]))
    return next(iter(zeros + (rest if free else [])), None)


def insert_in_preheader(pre: Block, line: Line) -> None:
    at = len(pre.lines)
    last = pre.last_instr()
    if last is not None and last.op == "BRA" and pre.lines[-1] is last:
        at -= 1                                   # antes del salto que entra al bucle
    pre.lines.insert(at, line)


def move_group(key: Key, members: list[Candidate], facts: Reaching, pre: Block, free: list[int],
               stats: dict) -> None:
    """Calcula una vez en el preheader y hace que los usos lean el resultado; borra las originales."""
    if is_zero(key):
        name = "R0"
        stats["licm.zeros"] = stats.get("licm.zeros", 0) + 1
    else:
        name = f"R{free[0]}"
        stats["licm.registers"] = stats.get("licm.registers", 0) + 1
        insert_in_preheader(pre, instr(key[0], name, *members[0][1].args[1:]))
    for block, line in members:
        t = reg(line.args[0])
        for use, _ in facts.uses_of[id(line)]:
            for slot in use_slots(use) or []:
                if reg_of(use.args[slot]) == t:
                    use.args[slot] = name
        block.lines = [l for l in block.lines if l is not line]
        stats["licm.removed"] = stats.get("licm.removed", 0) + 1


def licm_loop(blocks: list[Block], body: set[int], header: int, pre: Block, allowed: list[int],
              stats: dict, readonly: frozenset[str] = frozenset()) -> None:
    """Saca lo invariante de un bucle hasta que no quede nada que sacar o registros."""
    loads_ok = (lambda line: invariant_load_ok(line, pre, readonly)) if readonly else None
    while True:
        live_in = live_in_blocks(blocks, liveness(blocks))
        facts = reaching_in_loop(blocks, body)
        groups = invariant_groups(blocks, body, facts, live_in, loads_ok)
        free = free_registers(blocks, body, header, allowed, live_in)
        key = choose_group(groups, free)
        if key is None:
            return
        move_group(key, groups[key], facts, pre, free, stats)


def preheader(blocks: list[Block], header: int, body: set[int]) -> Block | None:
    """El unico bloque de fuera del bucle que entra en el, si solo va a el."""
    outside = [b for b in predecessors(blocks)[header] if b not in body]
    if len(outside) != 1 or blocks[outside[0]].succ != [header]:
        return None
    return blocks[outside[0]]


@register_pass("licm", "saca de los bucles lo que no cambia en ellos (constantes y cuentas con valores fijos)")
def pass_licm(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if len(blocks) < 2:
            continue
        loops = natural_loops(blocks, dominators(blocks))
        kernel = function.name.startswith(KERNEL_PREFIX)
        readonly = frozenset(readonly_symbols(blocks)) if NOALIAS and kernel else frozenset()
        # primero los temporales, luego los de argumentos y el enlace (la vida de registros dice cuando
        # estan libres: R1/R2 al retornar, R31 hasta su `JR`), y en un kernel los preservados sin uso
        allowed = list(range(5, 16)) + [1, 2, 3, 4, 31] + (list(range(16, 30)) if kernel else [])
        # de dentro afuera: lo que el bucle interior deja en su preheader esta en el cuerpo del exterior, y si
        # tampoco cambia alli (las constantes, la base de una tabla, 4 * lane) sube otra vez
        for header, body in sorted(loops.items(), key=lambda item: (len(item[1]), item[0])):
            if any(l.kind == "instr" and l.op in ("JAL", "JALR") for b in body for l in blocks[b].lines):
                continue
            pre = preheader(blocks, header, body)
            if pre is None:
                continue
            before = stats.get("licm.removed", 0)
            licm_loop(blocks, body, header, pre, allowed, stats, readonly)
            if stats.get("licm.removed", 0) > before:
                stats["licm.loops"] = stats.get("licm.loops", 0) + 1
        function.body = [line for block in blocks for line in block.lines]
