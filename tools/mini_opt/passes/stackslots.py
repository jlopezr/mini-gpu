"""Promocion de huecos de pila a registros

lcc reparte los registros por orden de declaracion y deja en la pila lo que no cabe. En un kernel
cada lane tiene su porcion de pila a 512 bytes de la siguiente, asi que un acceso de un warp son 8
transacciones y no una; en el cubo, la fila, la lane y el paso del bucle de filas se leen y escriben
6 veces por fila. Este pase lleva esos huecos a registros que la funcion no usa:

    LOAD Rd, R30, k     ->   ADD Rd, Rp, R0
    STORE Rs, R30, k    ->   ADD Rp, Rs, R0

y deja que `constprop` y `copyprop` (que van despues) quiten las copias. Cuando ya no queda ningun
acceso a la pila, tambien desaparece el marco: los `ADDI R30, R30, +-n` y, en un kernel, la
preparacion de la pila de la lane.

Un hueco se puede promocionar si es una palabra a un desplazamiento fijo de `R30` y todos sus
accesos son `LOAD`/`STORE` de palabra con `R30` de base (nadie le toma la direccion), y si alguno esta
en un bucle; los que no estan en ninguno solo se llevan si caben todos y el marco entero desaparece.
Para saber a que hueco apunta cada acceso se sigue cuanto vale `R30` (el marco baja y sube
con `ADDI`); si dos caminos llegan con valores distintos, o `R30` se toca de otra forma que en la
preparacion del principio, la funcion se deja como esta. Los registros son los que ninguna instruccion
de la funcion menciona: en un funcion normal solo los de llamante (R1..R15) y si no hay llamadas; en un
kernel, tambien R31 y los R16..R29 que sobren (a un kernel no le hace falta preservarlos)."""
from __future__ import annotations

from ..dead import remove_dead
from ..flow import Block, build_cfg, dominators, natural_loops
from ..isa import LOADS, STACK, STORES, defs_uses, number, reg_of
from ..model import Function, Line, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX

WORD = {"LOAD", "STORE"}
# el orden va al reves del de `licm` y `sharebase` (R5..R15, R1..R4, R31) para dejarles los suyos
KERNEL_REGISTERS = [31, 4, 3, 2, 1, *range(15, 4, -1), *range(29, 15, -1)]
LEAF_REGISTERS = [4, 3, 2, 1, *range(15, 4, -1)]


def is_adjust(line: Line) -> bool:
    return line.kind == "instr" and line.op == "ADDI" and len(line.args) == 3 and \
        reg_of(line.args[0]) == STACK and reg_of(line.args[1]) == STACK and number(line.args[2]) is not None


def frame_offsets(blocks: list[Block]) -> dict[int, int] | None:
    """Cuanto vale `R30` antes de cada instruccion, respecto a como estaba tras la preparacion del principio
    (`id(linea) -> desplazamiento`). None si dos caminos no coinciden o `R30` se toca de otra forma."""
    entering: dict[int, int] = {0: 0}
    at: dict[int, int] = {}
    work = [0]
    while work:
        b = work.pop()
        delta = entering[b]
        for line in blocks[b].lines:
            if line.kind != "instr":
                continue
            at[id(line)] = delta
            if STACK in defs_uses(line)[0]:
                if is_adjust(line):
                    delta += number(line.args[2])
                elif b == 0:
                    delta = 0                            # la preparacion de la pila de la lane: nuevo origen
                else:
                    return None
        for s in blocks[b].succ:
            if s not in entering:
                entering[s] = delta
                work.append(s)
            elif entering[s] != delta:
                return None
    return at


def slot_accesses(blocks: list[Block], at: dict[int, int]) -> dict[int, list[tuple[Block, Line]]] | None:
    """Accesos a cada hueco (por su posicion respecto al origen). None si algo toca la pila de otra forma."""
    slots: dict[int, list[tuple[Block, Line]]] = {}
    setup_over = False                                   # la preparacion del origen va antes de todo acceso
    for block in blocks:
        for line in block.lines:
            if line.kind != "instr":
                continue
            defs, uses = defs_uses(line)
            if line.op in ("EXIT", "HALT", "TRAP", "JR"):
                continue                                 # leen R30 por convenio, no por una direccion
            if STACK in defs:
                if not is_adjust(line) and setup_over:
                    return None
                continue
            if STACK not in uses:
                continue
            if line.op not in WORD or len(line.args) != 3 or reg_of(line.args[1]) != STACK \
                    or reg_of(line.args[0]) == STACK or number(line.args[2]) is None:
                return None                              # una direccion, un acceso de byte...
            if id(line) not in at:
                return None                              # codigo al que no llega ningun camino
            setup_over = True
            position = at[id(line)] + number(line.args[2])
            if position % 4:
                return None
            slots.setdefault(position, []).append((block, line))
    return slots


def loop_depths(blocks: list[Block]) -> dict[int, int]:
    loops = natural_loops(blocks, dominators(blocks))
    return {b.index: sum(b.index in body for body in loops.values()) for b in blocks}


def unused_registers(function: Function, blocks: list[Block], kernel: bool) -> list[int]:
    """Registros que ninguna instruccion de la funcion menciona y que se pueden usar sin guardarlos."""
    mentioned: set[int] = set()
    calls = False
    for block in blocks:
        for line in block.lines:
            if line.kind != "instr":
                continue
            calls = calls or line.op in ("JAL", "JALR")
            if kernel and line.op == "EXIT":
                continue                                 # nadie recibe lo que un kernel deja en los preservados
            mentioned |= set().union(*defs_uses(line))
    if kernel:
        candidates = KERNEL_REGISTERS
    else:
        candidates = [] if calls else LEAF_REGISTERS
    return [r for r in candidates if r not in mentioned]


def promote(function: Function, stats: dict) -> None:
    blocks = build_cfg(function)
    if not blocks:
        return
    kernel = function.name.startswith(KERNEL_PREFIX)
    at = frame_offsets(blocks)
    slots = slot_accesses(blocks, at) if at is not None else None
    if not slots:
        return
    # Desde +16 respecto al R30 de entrada empieza el area de argumentos que
    # no caben en R1-R4. Son valores aportados por el llamador, no slots
    # privados inicializados por esta funcion: promoverlos produciria un
    # registro sin inicializar (`sum5`, structs por valor, varargs...).
    slots = {position: accesses for position, accesses in slots.items() if position < 16}
    if not slots:
        return
    depth = loop_depths(blocks)
    weight = {p: sum(10 ** depth[b.index] for b, _ in accesses) for p, accesses in slots.items()
              if any(depth[b.index] for b, _ in accesses)}
    free = unused_registers(function, blocks, kernel)
    hot = sorted(weight, key=lambda p: -weight[p])
    chosen = dict(zip(hot, free))
    cold = [p for p in slots if p not in chosen]
    if cold and len(chosen) == len(hot) and len(cold) <= len(free) - len(chosen):
        chosen.update(zip(cold, free[len(chosen):]))        # si caben todos, el marco entero desaparece
    if not chosen:
        return
    for position, register in chosen.items():
        for _, line in slots[position]:
            if line.op in LOADS:
                line.op, line.args = "ADD", [line.args[0], f"R{register}", "R0"]
            else:
                line.op, line.args = "ADD", [f"R{register}", line.args[0], "R0"]
            stats["stackslots.accesses"] = stats.get("stackslots.accesses", 0) + 1
        stats["stackslots.slots"] = stats.get("stackslots.slots", 0) + 1
    remove_frame(blocks, at, kernel, stats)
    remove_dead(blocks, stats, "stackslots")
    function.body = [line for block in blocks for line in block.lines]


def remove_frame(blocks: list[Block], at: dict[int, int], kernel: bool, stats: dict) -> None:
    """Si nadie lee ya `R30` como base, el marco no sirve: fuera los `ADDI R30, R30, n` (suman cero por cada
    camino de salida) y, en un kernel, la preparacion de la pila de la lane."""
    reads = [line for block in blocks for line in block.lines
             if line.kind == "instr" and STACK in defs_uses(line)[1] and not is_setup(line)
             and line.op not in ("EXIT", "HALT", "TRAP", "JR")]
    if reads:
        return
    exits = [line for block in blocks for line in block.lines
             if line.kind == "instr" and line.op in ("JR", "HALT", "TRAP")]
    if not kernel and any(at.get(id(line)) not in (0, None) for line in exits):
        return                                           # el marco no se devuelve entero: no lo toco
    removed = 0
    for block in blocks:
        keep = []
        for line in block.lines:
            if line.kind == "instr" and STACK in defs_uses(line)[0] and (kernel or is_adjust(line)):
                removed += 1
                continue
            keep.append(line)
        block.lines = keep
    if removed:
        stats["stackslots.frames"] = stats.get("stackslots.frames", 0) + 1


def is_setup(line: Line) -> bool:
    """Una instruccion que escribe R30 (el ajuste del marco o la preparacion de la pila): no lo lee de base."""
    return STACK in defs_uses(line)[0]


@register_pass("stackslots", "huecos de la pila de la lane que se leen en bucles, a registros libres")
def pass_stackslots(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        promote(function, stats)
