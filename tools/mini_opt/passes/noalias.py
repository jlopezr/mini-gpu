"""`__noalias_mark`: punteros sin alias, a la manera de `restrict` (que C89 no tiene)

    int *fb = ...;  NOALIAS(fb);          /* gpu.h: __noalias_mark = (int)fb; */

El pase `intrinsics` convierte esa escritura en `NOALIAS Rfb`, una instruccion interna que lee el puntero (para que
siga vivo hasta ella) y que este pase borra al final. Mientras tanto, el analisis de procedencia de aqui dice, de
cada registro, de que punteros marcados puede derivar su valor. Es la promesa de `restrict`: lo que se accede por
un puntero marcado `p` (o por otro calculado a partir de el) no se accede por ninguno que no derive de `p`, mientras
dure la funcion. Dos accesos por punteros que no pueden ser el mismo objeto no se estorban, y `licm` puede sacar de
un bucle una lectura invariante aunque haya stores.

La procedencia de un registro es un conjunto de marcas (cada `NOALIAS` es una region nueva):
  - la marca vale para el VALOR del puntero, no para el registro al que se le pasa: lcc deja el mismo valor en otros
    registros (`ADD R10, R1, R0 ; NOALIAS R10` y luego usa R1) y en huecos de la pila (el prologo vuelca R1 a su
    hueco). Cada valor lleva un numero (una copia lo conserva y cualquier otra definicion estrena uno), y toda
    aparicion del valor marcado lleva la region, tambien antes de la marca;
  - una operacion aritmetica (`ADD`, `ADDI`, `SHL`...) da la union de las de sus operandos: `p + indice` deriva de `p`;
  - una constante, una direccion de simbolo o un id de hilo no derivan de nada: conjunto vacio;
  - lo que se carga de memoria deriva de las regiones que se hayan guardado en memoria, pasado a una llamada o
    devuelto (se "escapan"): un puntero marcado que se guarda y se vuelve a leer sigue siendo el mismo objeto;
  - lo que devuelve una llamada, igual.
Los huecos de la pila se tratan como propios de la funcion: ningun puntero los pisa. Un puntero que se carga de
memoria sin haber pasado por la marca (otra lectura del mismo sitio) es un puntero distinto, aunque valga lo mismo:
usarlo para tocar el objeto marcado es una promesa rota, como en `restrict`.

Dos accesos no se estorban si sus procedencias no comparten ninguna region y al menos una no esta vacia: dos
accesos sin marca no dicen nada el uno del otro.

Si el programador marca mal (dos marcas sobre punteros que apuntan al mismo objeto, o un acceso al objeto por un
puntero que no deriva de la marca), el resultado es incorrecto sin aviso, como en `restrict`."""
from __future__ import annotations

from ..flow import Block, predecessors
from ..isa import IMM2, LOADS, R3, STORES, WRITE_ONLY1, defs_uses, number, reg, reg_of
from ..model import Unit
from ..registry import register_pass

MARK = "NOALIAS"
Tags = dict[int, frozenset]
EMPTY: frozenset = frozenset()
# Claves del estado, ademas de 0..31 (procedencia del registro): VALUE + r = numero de valor de Rr.
VALUE = 100


def marks(blocks: list[Block]) -> list:
    return [line for block in blocks for line in block.lines if line.kind == "instr" and line.op == MARK]


class Context:
    """Lo que el analisis supone y va descubriendo: las regiones escapadas y los valores marcados."""

    def __init__(self, numbered: dict[int, int]) -> None:
        self.numbered = numbered
        self.escaped: frozenset = EMPTY
        self.region_of: dict[int, frozenset] = {}           # numero de valor -> regiones
        self.leaked: set = set()                            # lo que esta pasada ve salir a memoria o a una llamada
        self.marked: dict[int, set] = {}                    # numero de valor -> regiones que esta pasada le marca


def value_of(state: Tags, register: int | None) -> int | None:
    found = state.get(VALUE + register) if register else None
    return next(iter(found)) if found is not None and len(found) == 1 else None


def tag_of(state: Tags, register: int | None, ctx: Context) -> frozenset:
    if not register:
        return EMPTY
    value = value_of(state, register)
    return state.get(register, EMPTY) | (ctx.region_of.get(value, EMPTY) if value is not None else EMPTY)


def entry_state() -> Tags:
    """Al entrar, R1..R4 traen el valor de los argumentos: uno distinto cada uno."""
    return {VALUE + r: frozenset({-r}) for r in (1, 2, 3, 4)}


def is_copy(line) -> int | None:
    """El registro del que `line` copia su valor (`ADD d, a, R0`, `ADDI d, a, 0`), o None."""
    args = line.args
    if line.op == "ADD" and len(args) == 3:
        a, b = reg_of(args[1]), reg_of(args[2])
        if b == 0:
            return a
        if a == 0:
            return b
    if line.op == "ADDI" and len(args) == 3 and number(args[2]) == 0:
        return reg_of(args[1])
    return None


def step(state: Tags, line, ctx: Context) -> None:
    """Actualiza `state` con una instruccion."""
    op, args = line.op, line.args
    if op == MARK:
        region = frozenset({ctx.numbered[id(line)]})
        v = reg(args[0])
        value = value_of(state, v)
        if value is not None:
            ctx.marked.setdefault(value, set()).update(region)
        state[v] = state.get(v, EMPTY) | region
        return
    defs, _ = defs_uses(line)
    if op in STORES and len(args) == 3:
        ctx.leaked |= tag_of(state, reg_of(args[0]), ctx)       # el valor que se guarda
        return
    if op in ("JAL", "JALR"):
        for r in (1, 2, 3, 4):
            ctx.leaked |= tag_of(state, r, ctx)         # los argumentos de la llamada
    if op in R3 or op in IMM2:
        result = EMPTY
        for source in args[1:]:
            result = result | tag_of(state, reg_of(source), ctx)
        copy_of = is_copy(line)
        for d in defs:
            fresh = state[VALUE + copy_of] if copy_of is not None and VALUE + copy_of in state else frozenset({id(line)})
            state[d] = result
            state[VALUE + d] = fresh
    elif op in WRITE_ONLY1:
        for d in defs:
            state[d] = EMPTY
            state[VALUE + d] = frozenset({id(line)})
    else:                                               # cargas, llamadas...: lo que haya escapado
        for d in defs:
            state[d] = ctx.escaped
            state[VALUE + d] = frozenset({id(line)})


def join(states: list[Tags]) -> Tags:
    merged: Tags = {}
    for state in states:
        for key, tags in state.items():
            merged[key] = merged.get(key, EMPTY) | tags
    return merged


def analyse(blocks: list[Block], ctx: Context) -> dict[int, Tags]:
    """Procedencia antes de cada carga o store, con lo que `ctx` supone; deja en `ctx` lo que descubre."""
    out: list[Tags | None] = [None] * len(blocks)
    preds = predecessors(blocks)

    def entering(block: Block) -> Tags | None:
        states = [out[p] for p in preds[block.index] if out[p] is not None]
        if block.index == 0:
            states.append(entry_state())
        return join(states) if states else None

    changed = True
    while changed:
        changed = False
        for block in blocks:
            state = entering(block)
            if state is None:
                continue
            for line in block.lines:
                if line.kind == "instr":
                    step(state, line, ctx)
            if state != out[block.index]:
                out[block.index] = state
                changed = True
    ctx.leaked = set()
    ctx.marked = {}
    snapshot: dict[int, Tags] = {}
    for block in blocks:
        state = entering(block)
        if state is None:
            continue
        for line in block.lines:
            if line.kind != "instr":
                continue
            if line.op in LOADS or line.op in STORES:
                snapshot[id(line)] = dict(state)
            step(state, line, ctx)
    return snapshot


Found = tuple[dict[int, Tags], Context]


def provenance(blocks: list[Block]) -> Found | None:
    """(estado antes de cada carga o store por `id(linea)`, el `Context` para leerlo); None si no hay marcas."""
    numbered = {id(line): n for n, line in enumerate(marks(blocks))}
    if not numbered:
        return None
    ctx = Context(numbered)
    while True:
        snapshot = analyse(blocks, ctx)
        escaped = ctx.escaped | frozenset(ctx.leaked)
        region_of = {v: ctx.region_of.get(v, EMPTY) | frozenset(r) for v, r in ctx.marked.items()}
        for v, r in ctx.region_of.items():
            region_of[v] = region_of.get(v, EMPTY) | r
        if escaped == ctx.escaped and region_of == ctx.region_of:
            return snapshot, ctx
        ctx.escaped, ctx.region_of = escaped, region_of


def no_alias(a: frozenset, b: frozenset) -> bool:
    """Dos accesos con estas procedencias no pueden tocar el mismo objeto."""
    return not (a & b) and bool(a | b)


def access_tag(found: Found, line) -> frozenset:
    snapshot, ctx = found
    return tag_of(snapshot[id(line)], reg_of(line.args[1]), ctx)


def loop_stores_apart(blocks: list[Block], body: set[int], found: Found, load) -> bool:
    """Ningun store del bucle puede tocar lo que lee `load` (que va por un puntero marcado o por un simbolo)."""
    wanted = access_tag(found, load)
    for b in body:
        for line in blocks[b].lines:
            if line.kind != "instr" or line.op not in STORES or len(line.args) != 3:
                continue
            if reg_of(line.args[1]) == 30:
                continue                    # el marco de la funcion no es de nadie mas
            if not no_alias(wanted, access_tag(found, line)):
                return False
    return True


@register_pass("noalias", "borra las marcas internas de `__noalias_mark` (ya las uso `licm`)")
def pass_noalias(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        function.body = [line for line in function.body if not (line.kind == "instr" and line.op == MARK)]
