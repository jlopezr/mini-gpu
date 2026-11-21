"""Subexpresiones comunes, cargas incluidas, con los alias de lcc (`; @miniopt alias`)

    SHLI R12, R27, 2 ; LOAD R11, R14, 0 ; ADD R12, R12, R11 ; LOAD R12, R12, 0      (y[i])
    BGE R12, R0, L
  L:
    SHLI R12, R27, 2 ; LOAD R11, R14, 0 ; ADD R12, R12, R11 ; LOAD R12, R12, 0      (y[i] otra vez)

lcc recalcula cada `y[i]` entero, carga del puntero `y` incluida: no tiene subexpresiones comunes entre sentencias.
Este pase sigue el valor de cada registro como un arbol sobre registros que no han cambiado (`R27`, `R14`) y sobre
la memoria que no se ha escrito (`LOAD(R14, 0)`), y con eso:

  - si un registro ya tiene el valor de una instruccion, la instruccion pasa a una copia (`ADD d, h, R0`), y
    `copyprop`/`dce` se llevan la copia y la cuenta que la alimentaba;
  - tras `STORE v, A` (una palabra, anotada y no volatile), una carga de palabra de `A` con la misma etiqueta
    lee `v` (si la direccion incluye una carga que el propio store puede pisar, no);
  - si el valor se calculo en todos los caminos y nadie lo conserva (lcc reutiliza R12 para todo), en un bucle,
    las instrucciones que lo calcularon lo copian ademas a un registro libre en todo ese tramo, y la de ahora lo lee
    de alli.

Una escritura en memoria mata los valores cargados que puede pisar. Lo que no se solapa:
  - dos accesos con la misma base (el mismo arbol) y rangos de bytes disjuntos;
  - dos etiquetas de lcc de clases distintas entre `global:`, `fresh:` y `local:` (un global no es un objeto de la
    pila ni lo que devuelve `malloc`), o dos `global:`/`fresh:` distintas. Dos `local:` solo por la direccion: un
    `inline` puede haber juntado marcos;
  - un acceso a la pila (base R30) y uno `global:` o `fresh:`.
Una llamada, o cualquier instruccion que no se conoce, mata todo lo cargado. Solo entra en un arbol la carga que
lcc anoto y que no es volatile (ni de un simbolo `; @miniopt volatile`): sin anotacion puede ser un registro de un
dispositivo. Los kernels de GPU no se tocan (otras lanes escriben la memoria compartida)."""
from __future__ import annotations

from functools import lru_cache

from ..flow import Block, build_cfg, dominators, live_in_blocks, liveness, natural_loops, predecessors
from ..isa import BRANCHES, IMM2, LOADS, PURE_OPS, R3, STORES, UNARY, defs_uses, instr, number, reg_of
from ..model import Line, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX

Tree = tuple
ZERO: Tree = ("K", "0")
COMMUTATIVE = {"ADD", "MUL", "AND", "OR", "XOR", "MIN", "MAX", "MINU", "MAXU", "MULHI"}
WIDTH = {"LOAD": 4, "LOADB": 1, "LOADUB": 1, "LOADH": 2, "LOADUH": 2, "STORE": 4, "STOREB": 1, "STOREH": 2}
HARMLESS = BRANCHES | {"BRA", "JR", "NOALIAS", "CLOBBER", "DIV", "DIVU", "REM", "REMU", "HALT", "TRAP", "EXIT"}
MAX_NODES = 16
MAX_SPARES = 32                     # transformaciones con registro libre por funcion (cada una rehace el analisis)
STACK = ("R", 30)


@lru_cache(maxsize=None)
def leaves(tree: Tree) -> frozenset[int]:
    if tree[0] == "R":
        return frozenset((tree[1],))
    if tree[0] in ("K", "I"):
        return frozenset()
    out: frozenset[int] = frozenset()
    for child in tree[1:]:
        if isinstance(child, tuple):
            out |= leaves(child)
    return out


@lru_cache(maxsize=None)
def nodes(tree: Tree) -> int:
    if tree[0] in ("R", "K", "I"):
        return 1
    return 1 + sum(nodes(child) for child in tree[1:] if isinstance(child, tuple))


@lru_cache(maxsize=None)
def loads_in(tree: Tree) -> tuple[Tree, ...]:
    if tree[0] in ("R", "K", "I"):
        return ()
    out: tuple[Tree, ...] = (tree,) if tree[0] == "LD" else ()
    for child in tree[1:]:
        if isinstance(child, tuple):
            out += loads_in(child)
    return out


def tag_kind(tag: str | None) -> str:
    return tag.split(":", 1)[0] if tag else "unknown"


def disjoint(load: Tree, store: tuple) -> bool:
    """`load` es ('LD', op, base, offset, etiqueta); `store`, (op, base, offset, etiqueta)."""
    _, lop, lbase, loff, ltag = load
    sop, sbase, soff, stag = store
    if lbase == sbase:
        a, b = number(loff), number(soff)
        if a is not None and b is not None and (a + WIDTH[lop] <= b or b + WIDTH[sop] <= a):
            return True
    lk, sk = tag_kind(ltag), tag_kind(stag)
    if lk in ("global", "fresh", "local") and sk in ("global", "fresh", "local"):
        if lk != sk:
            return True
        if lk != "local" and ltag != stag:
            return True
    if (lbase == STACK and sk in ("global", "fresh")) or (sbase == STACK and lk in ("global", "fresh")):
        return True
    return False


class State:
    """Lo que vale cada registro (`val`: registro -> arbol; sin entrada, no se sabe), los arboles ya calculados
    en todos los caminos que siguen valiendo (`avail`) y lo escrito en memoria que sigue en un registro
    (`stored`: el arbol de la carga que lo leeria -> el registro que se guardo)."""
    __slots__ = ("val", "avail", "stored")

    def __init__(self, val: dict[int, Tree] | None = None, avail: set[Tree] | None = None,
                 stored: dict[Tree, int] | None = None):
        self.val = val if val is not None else {}
        self.avail = avail if avail is not None else set()
        self.stored = stored if stored is not None else {}

    def copy(self) -> "State":
        return State(dict(self.val), set(self.avail), dict(self.stored))

    def __eq__(self, other) -> bool:
        return self.val == other.val and self.avail == other.avail and self.stored == other.stored

    def tree_of(self, arg: str) -> Tree | None:
        r = reg_of(arg)
        if r is None:
            return None
        if r == 0:
            return ZERO
        return self.val.get(r, ("R", r))

    def kill_register(self, r: int) -> None:
        for q in [q for q, t in self.val.items() if r in leaves(t)]:
            del self.val[q]
        self.val.pop(r, None)
        self.avail = {t for t in self.avail if r not in leaves(t)}
        self.stored = {t: h for t, h in self.stored.items() if h != r and r not in leaves(t)}

    def kill_memory(self, store: tuple | None) -> None:
        """`store` None: todo lo cargado."""
        def survives(tree: Tree) -> bool:
            return all(store is not None and disjoint(load, store) for load in loads_in(tree))
        self.val = {q: t for q, t in self.val.items() if survives(t)}
        self.avail = {t for t in self.avail if survives(t)}
        self.stored = {t: h for t, h in self.stored.items() if survives(t)}


def join(states: list[State]) -> State:
    first = states[0]
    val = {q: t for q, t in first.val.items() if all(s.val.get(q) == t for s in states[1:])}
    avail = set(first.avail)
    for s in states[1:]:
        avail &= s.avail
    stored = {t: h for t, h in first.stored.items() if all(s.stored.get(t) == h for s in states[1:])}
    return State(val, avail, stored)


class Analysis:
    def __init__(self, unit: Unit):
        self.volatile = unit.volatile

    def loadable(self, line: Line) -> bool:
        return self.tag_ok(line.alias)

    def tag_ok(self, alias: str | None) -> bool:
        if not alias or alias.endswith(" volatile"):
            return False
        return not (alias.startswith("global:") and alias[7:] in self.volatile)

    def tree(self, state: State, line: Line) -> Tree | None:
        """El arbol del valor que escribe `line`, con los operandos de antes; None si no se modela."""
        op, args = line.op, line.args
        if op in LOADS:
            if len(args) != 3 or not self.loadable(line):
                return None
            base = state.tree_of(args[1])
            if base is None:
                return None
            tree = ("LD", op, base, args[2].replace(" ", ""), line.alias)
        elif op in ("MOVI", "LI") and len(args) == 2:
            return ("K", args[1].replace(" ", ""))
        elif op in R3 and op in PURE_OPS and len(args) == 3:
            a, b = state.tree_of(args[1]), state.tree_of(args[2])
            if a is None or b is None:
                return None
            if op == "ADD" and b == ZERO:
                return a
            if op == "ADD" and a == ZERO:
                return b
            if op in COMMUTATIVE and repr(b) < repr(a):
                a, b = b, a
            tree = (op, a, b)
        elif op in IMM2 and len(args) == 3:
            a = state.tree_of(args[1])
            if a is None:
                return None
            if op == "ADDI" and number(args[2]) == 0:
                return a
            tree = (op, a, ("I", args[2].replace(" ", "")))
        elif op in UNARY and len(args) >= 2:
            a = state.tree_of(args[1])
            if a is None:
                return None
            tree = (op, a, *(("I", x.replace(" ", "")) for x in args[2:]))
        else:
            return None
        return tree if nodes(tree) <= MAX_NODES else None

    def step(self, state: State, line: Line) -> Tree | None:
        """Aplica `line` a `state`; devuelve el arbol que ha escrito (o None)."""
        if line.kind != "instr":
            return None
        op = line.op
        tree = self.tree(state, line)
        if op in STORES:
            if len(line.args) == 3 and (base := state.tree_of(line.args[1])) is not None:
                store = (op, base, line.args[2].replace(" ", ""), line.alias)
                state.kill_memory(store)
                value = reg_of(line.args[0])
                if op == "STORE" and value is not None and self.tag_ok(line.alias) and \
                        all(disjoint(load, store) for load in loads_in(base)):
                    state.stored[("LD", "LOAD", base, store[2], line.alias)] = value
            else:
                state.kill_memory(None)
        elif op not in PURE_OPS and op not in LOADS and op not in HARMLESS:
            state.kill_memory(None)                         # llamadas y lo que no se conoce
        defs = defs_uses(line)[0]
        for r in defs:
            state.kill_register(r)
        if tree is not None and len(defs) == 1:
            (d,) = defs
            if d not in leaves(tree):
                state.val[d] = tree
                if tree[0] not in ("R", "K") and (loads_in(tree) or nodes(tree) >= 3):
                    state.avail.add(tree)
            return tree
        return None

    def solve(self, blocks: list[Block]) -> list[State | None]:
        preds = predecessors(blocks)
        order = reverse_postorder(blocks)
        ins: list[State | None] = [None] * len(blocks)
        outs: list[State | None] = [None] * len(blocks)
        changed = True
        while changed:
            changed = False
            for b in order:
                if b == 0:
                    state = State()
                else:
                    known = [outs[p] for p in preds[b] if outs[p] is not None]
                    if not known:
                        continue
                    state = join(known)
                ins[b] = state.copy()
                for line in blocks[b].lines:
                    self.step(state, line)
                if outs[b] is None or outs[b] != state:
                    outs[b] = state
                    changed = True
        return ins


def reverse_postorder(blocks: list[Block]) -> list[int]:
    seen: set[int] = set()
    order: list[int] = []
    stack = [(0, iter(blocks[0].succ))] if blocks else []
    seen.add(0)
    while stack:
        b, it = stack[-1]
        nxt = next((s for s in it if s not in seen), None)
        if nxt is None:
            order.append(b)
            stack.pop()
        else:
            seen.add(nxt)
            stack.append((nxt, iter(blocks[nxt].succ)))
    order.reverse()
    return order


def copy_line(dest: str, src: str, model: Line) -> Line:
    line = instr("ADD", dest, src, "R0")
    line.origin = model.origin
    return line


def reuse_held(blocks: list[Block], analysis: Analysis, ins: list, stats: dict) -> list[tuple[int, Line, Tree]]:
    """Las instrucciones cuyo valor ya tiene un registro pasan a copia. Devuelve las que tienen el valor calculado
    en todos los caminos pero en ningun registro: (bloque, linea, arbol)."""
    lost: list[tuple[int, Line, Tree]] = []
    for block in blocks:
        state = ins[block.index]
        if state is None:
            continue
        state = state.copy()
        for k, line in enumerate(block.lines):
            if line.kind != "instr":
                continue
            tree = analysis.tree(state, line)
            defs = defs_uses(line)[0]
            if tree is not None and tree[0] not in ("R", "K") and len(defs) == 1:
                (d,) = defs
                holder = next((h for h, t in sorted(state.val.items()) if t == tree), state.stored.get(tree))
                if holder == d:
                    block.lines[k] = line = copy_line(f"R{d}", f"R{d}", line)    # ya lo tiene: dce la borra
                    stats["cse.reused"] = stats.get("cse.reused", 0) + 1
                elif holder is not None:
                    block.lines[k] = line = copy_line(line.args[0], f"R{holder}", line)
                    stats["cse.reused"] = stats.get("cse.reused", 0) + 1
                elif tree in state.avail:
                    lost.append((block.index, line, tree))
            analysis.step(state, line)
    return lost


def computes(analysis: Analysis, state: State, line: Line, tree: Tree) -> bool:
    return line.kind == "instr" and analysis.tree(state, line) == tree and len(defs_uses(line)[0]) == 1


def definitions(blocks: list[Block], analysis: Analysis, ins: list, b0: int, target: Line,
                tree: Tree) -> tuple[list[tuple[int, Line]], set[int]] | None:
    """Las ultimas instrucciones que calculan `tree` en cada camino que llega a `target`, y los bloques del tramo."""
    preds = predecessors(blocks)

    def scan(b: int, stop: Line | None) -> Line | None:
        state = ins[b].copy() if ins[b] is not None else None
        if state is None:
            return None
        found = None
        for line in blocks[b].lines:
            if line is stop:
                break
            if computes(analysis, state, line, tree):
                found = line
            analysis.step(state, line)
        return found

    defs: list[tuple[int, Line]] = []
    region: set[int] = {b0}
    first = scan(b0, target)
    if first is not None:
        return [(b0, first)], region
    work = list(preds[b0])
    seen: set[int] = set()
    while work:
        b = work.pop()
        if b in seen:
            continue
        seen.add(b)
        region.add(b)
        found = scan(b, None)
        if found is not None:
            defs.append((b, found))
            continue
        if b == 0 or not preds[b]:
            return None
        work.extend(preds[b])
    return (defs, region) if defs else None


def spare_register(blocks: list[Block], region: set[int], allowed: list[int]) -> int | None:
    live_out = liveness(blocks)
    live_in = live_in_blocks(blocks, live_out)
    used: set[int] = set()
    for b in region:
        used |= live_in[b] | live_out[b]
        for line in blocks[b].lines:
            if line.kind == "instr":
                if line.op in ("JAL", "JALR"):
                    return None
                defs, uses = defs_uses(line)
                used |= defs | uses
    return next((r for r in allowed if r not in used), None)


def keep_lost(blocks: list[Block], analysis: Analysis, ins: list, lost: list, loop_blocks: set[int],
              allowed: list[int], stats: dict) -> bool:
    """Una transformacion con registro libre (la primera que se pueda). Devuelve si ha hecho alguna."""
    for b, line, tree in lost:
        if b not in loop_blocks:
            continue
        found = definitions(blocks, analysis, ins, b, line, tree)
        if found is None:
            continue
        defs, region = found
        spare = spare_register(blocks, region, allowed)
        if spare is None:
            continue
        for db, dline in defs:
            lines = blocks[db].lines
            at = next(i for i, l in enumerate(lines) if l is dline)
            lines.insert(at + 1, copy_line(f"R{spare}", dline.args[0], dline))
        lines = blocks[b].lines
        at = next(i for i, l in enumerate(lines) if l is line)
        lines[at] = copy_line(line.args[0], f"R{spare}", line)
        stats["cse.kept"] = stats.get("cse.kept", 0) + 1
        return True
    return False


@register_pass("cse", "subexpresiones comunes y cargas repetidas, con los alias de lcc (`; @miniopt alias`)")
def pass_cse(unit: Unit, stats: dict) -> None:
    analysis = Analysis(unit)
    for function in unit.functions():
        if function.opaque or function.name.startswith(KERNEL_PREFIX):
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        loops = natural_loops(blocks, dominators(blocks))
        loop_blocks = {b for body in loops.values() for b in body}
        allowed = list(range(7, 16)) + [1, 2, 3, 4, 5, 6]
        before = (stats.get("cse.reused", 0), stats.get("cse.kept", 0))
        for _ in range(MAX_SPARES + 1):
            ins = analysis.solve(blocks)
            lost = reuse_held(blocks, analysis, ins, stats)
            if not lost or not loop_blocks:
                break
            ins = analysis.solve(blocks)
            if not keep_lost(blocks, analysis, ins, lost, loop_blocks, allowed, stats):
                break
        if (stats.get("cse.reused", 0), stats.get("cse.kept", 0)) != before:
            stats["cse.functions"] = stats.get("cse.functions", 0) + 1
            function.body = [line for block in blocks for line in block.lines]
