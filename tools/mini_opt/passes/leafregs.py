"""En una funcion sin llamadas, los preservados (R16..R29) y R31 dejan de guardarse.

lcc reparte los registros de una funcion sin saber si los valores cruzan llamadas: en cuanto se le acaban los
R11..R15 (o hay una llamada en la funcion) usa R16..R29, y esos los tiene que devolver como estaban, asi que
los guarda en el prologo y los restaura en el epilogo. En una funcion que no llama a nadie (porque nunca llamo,
o porque `inline` expandio sus llamadas) eso sobra si queda algun R1..R15 libre. `stackslots` ya cambia el
guardado en la pila por una copia a un registro libre:

    ADD Rh, Rk, R0       ; entrada: guarda Rk en Rh
    ...                  ; el cuerpo usa Rk
    ADD Rk, Rh, R0       ; antes de cada JR: lo restaura

Si `Rh` no aparece en nada mas, este pase renombra `Rk` a `Rh` en toda la funcion y borra las copias: el cuerpo
hace lo mismo en `Rh`, que el llamador ya daba por perdido, y `Rk` no se toca, asi que vuelve como estaba. Con
R31 (el enlace, que solo lee el `JR`) basta con borrar las copias: sin llamadas, nadie lo escribe.

Lo que sigue guardado en la pila (`stackslots` solo lo pasa a copias si caben todos los huecos y el marco
desaparece) se trata igual: el `STORE Rk` del prologo y los `LOAD Rk` que lo restauran desde el mismo hueco se
borran y `Rk` pasa a un R3..R15 que la funcion no menciona, mientras queden (cada uno ahorra un `STORE` y un
`LOAD` por llamada). El de R31 se borra sin mas. Si al final nada lee la pila, el marco tambien se va.

Se comprueba con la vida de registros que el cuerpo renombrado no lee `Rh` antes de escribirlo (el `Rk` de
entrada no es un valor de la funcion; si lo leyera, no se toca). No se tocan los kernels (no devuelven nada:
`stackslots` ya les da los preservados sin guardarlos), los helpers de ABI privada ni las funciones que saltan
fuera de si mismas.
"""
from __future__ import annotations

from ..flow import build_cfg, live_in_entry, liveness
from ..isa import BRANCHES, CALLEE_SAVED, CALLER_SAVED, LINK, LOADS, STACK, STORES, defs_uses, number, reg_of
from ..model import Function, Line, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX
from .stackslots import frame_offsets, is_adjust, remove_frame

# Registros para los R16..R29 que se guardaban en la pila: R1 y R2 no (los lee el `JR`: son el resultado).
FREE_ORDER = (*range(15, 4, -1), 4, 3)


def is_copy(line: Line) -> tuple[int, int] | None:
    """(destino, origen) de un `ADD d, s, R0`."""
    if line.kind != "instr" or line.op != "ADD" or len(line.args) != 3 or reg_of(line.args[2]) != 0:
        return None
    dest, source = reg_of(line.args[0]), reg_of(line.args[1])
    return (dest, source) if dest is not None and source is not None else None


def is_leaf(function: Function) -> bool:
    """Sin llamadas y sin saltos fuera de la funcion."""
    labels = {line.name for line in function.body if line.kind == "label"}
    for line in function.body:
        if line.kind != "instr":
            continue
        if line.op in ("JAL", "JALR", "EXIT"):
            return False
        if line.op == "JR" and (len(line.args) != 1 or reg_of(line.args[0]) != LINK):
            return False
        if (line.op == "BRA" or line.op in BRANCHES) and line.args[-1] not in labels:
            return False
    return True


def mentions(line: Line) -> set[int]:
    return set().union(*defs_uses(line)) if line.kind == "instr" and line.op != "JR" else set()


def saved_copies(function: Function, register: int) -> tuple[int, list[Line]] | None:
    """El registro de la copia de `register` y las copias (la de entrada y las de vuelta), si `Rh` solo aparece en
    ellas: una que guarda y al menos una que restaura. El cuerpo puede tener otras copias de `Rk` (a temporales)."""
    for save in function.body:
        copy = is_copy(save)
        if not copy or copy[1] != register or copy[0] not in CALLER_SAVED:
            continue
        holder = copy[0]
        restores = [line for line in function.body if is_copy(line) == (register, holder)]
        copies = [save, *restores]
        pair = {id(line) for line in copies}
        if restores and not any(holder in mentions(line) for line in function.body if id(line) not in pair):
            return holder, copies
    return None


def renamed(line: Line, old: int, new: int) -> Line:
    if line.kind != "instr":
        return line
    args = [f"R{new}" if reg_of(arg) == old else arg for arg in line.args]
    return Line("instr", line.text, op=line.op, args=args)


def rename_into(function: Function, register: int, holder: int, drop: set[int], stats: dict) -> bool:
    """Borra las lineas de `drop` y renombra `register` a `holder` (con R31, solo borra). False si no se puede."""
    if register == LINK:
        if any(LINK in defs_uses(line)[0] for line in function.body
               if line.kind == "instr" and id(line) not in drop):
            return False
        body = [line for line in function.body if id(line) not in drop]
    else:
        body = [renamed(line, register, holder) for line in function.body if id(line) not in drop]
        blocks = build_cfg(Function(function.name, function.header, body))
        if blocks and holder in live_in_entry(blocks, liveness(blocks)):
            return False                                   # el cuerpo leia el Rk de entrada
    function.body = body
    stats["leafregs.registers"] = stats.get("leafregs.registers", 0) + 1
    return True


def free_copy(function: Function, register: int, stats: dict) -> bool:
    found = saved_copies(function, register)
    if found is None:
        return False
    holder, copies = found
    return rename_into(function, register, holder, {id(line) for line in copies}, stats)


def frame_saves(instructions: list[Line]) -> dict[int, tuple[Line, int]]:
    """{registro: (STORE, desplazamiento)} de los `STORE Rk, R30, off` (R16..R29 y R31) que siguen al
    `ADDI R30, R30, -n` del principio."""
    if not instructions or not is_adjust(instructions[0]):
        return {}
    saves: dict[int, tuple[Line, int]] = {}
    for line in instructions[1:]:
        register = reg_of(line.args[0]) if line.args else None
        offset = number(line.args[2]) if len(line.args) == 3 else None
        if (line.op != "STORE" or len(line.args) != 3 or reg_of(line.args[1]) != STACK
                or register not in (*CALLEE_SAVED, LINK) or offset is None or register in saves):
            break
        saves[register] = (line, offset)
    return saves


def slot_restores(register: int, offset: int, store: Line, instructions: list[Line]) -> list[Line] | None:
    """Los `LOAD Rk, R30, off` que restauran el hueco, si nada mas lo toca ni calcula su direccion."""
    restores: list[Line] = []
    for line in instructions:
        if line is store:
            continue
        if line.op in LOADS | STORES and len(line.args) == 3 and reg_of(line.args[1]) == STACK:
            at = number(line.args[2])
            if at is None:
                return None                                 # un desplazamiento simbolico: no se sabe donde cae
            if at == offset:
                if line.op != "LOAD" or reg_of(line.args[0]) != register:
                    return None                             # el hueco se usa para otra cosa
                restores.append(line)
        elif (line.op == "ADDI" and len(line.args) == 3 and reg_of(line.args[1]) == STACK
              and reg_of(line.args[0]) != STACK and number(line.args[2]) == offset):
            return None                                     # la direccion del hueco se calcula
    return restores or None


def interferes(function: Function, drop: set[int], a: int, b: int) -> bool:
    """`a` y `b` llevan a la vez valores que hacen falta (sin las lineas de `drop`): una instruccion escribe uno
    mientras el otro sigue vivo, salvo que sea la copia de uno al otro. Si no interfieren, pueden ser el mismo
    registro. El `JR` no cuenta como lectura de `a` (lo de dentro de la funcion no vuelve: se renombra a `b`), y
    `b` no puede ser R1 ni R2, que si lee."""
    body = []
    for line in function.body:
        if id(line) in drop:
            continue
        if line.kind == "instr" and line.op == "JR":
            line = Line("instr", "", op="BRA", args=["@salida"])       # termina el bloque sin leer nada
        body.append(line)
    blocks = build_cfg(Function(function.name, function.header, body))
    live_out = liveness(blocks)
    for block in blocks:
        live = set(live_out[block.index])
        for line in reversed(block.lines):
            if line.kind != "instr":
                continue
            defs, uses = defs_uses(line)
            copy = is_copy(line)
            for written, other in ((a, b), (b, a)):
                if written in defs and other in live and copy != (written, other):
                    return True
            live = (live - defs) | uses
    return False


def free_frame_saves(function: Function, stats: dict) -> bool:
    """Uno a uno: cada renombrado cambia las lineas, asi que los guardados se vuelven a buscar."""
    changed = False
    tried: set[int] = set()
    while True:
        instructions = [line for line in function.body if line.kind == "instr"]
        pending = [(register, save) for register, save in frame_saves(instructions).items() if register not in tried]
        if not pending:
            return changed
        register, (store, offset) = pending[0]
        tried.add(register)
        restores = slot_restores(register, offset, store, instructions)
        if restores is None:
            continue
        drop = {id(line) for line in [store, *restores]}
        holder = 0
        if register != LINK:
            holder = next((r for r in FREE_ORDER if not interferes(function, drop, register, r)), 0)
            if not holder:
                continue
        changed |= rename_into(function, register, holder, drop, stats)


def drop_empty_frame(function: Function, stats: dict) -> None:
    blocks = build_cfg(function)
    at = frame_offsets(blocks) if blocks else None
    if at is None:
        return
    remove_frame(blocks, at, False, stats)
    function.body = [line for block in blocks for line in block.lines]


@register_pass("leafregs", "funcion sin llamadas: los R16..R29 y R31 que guarda pasan a registros libres")
def pass_leafregs(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque or function.name.startswith(KERNEL_PREFIX) or not is_leaf(function):
            continue
        changed = False
        for register in (*CALLEE_SAVED, LINK):
            changed |= free_copy(function, register, stats)
        changed |= free_frame_saves(function, stats)
        if changed:
            drop_empty_frame(function, stats)
