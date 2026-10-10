"""Store-to-load forwarding sobre huecos de la pila

    STORE R1, R30, 32 ... LOAD R1, R30, 32     ->  (el LOAD sobra)
    STORE R1, R30, 32 ... LOAD R5, R30, 32     ->  ADD R5, R1, R0

lcc vuelca los argumentos R1..R4 a su hueco al entrar y los recarga uno a uno; los valores que derrama
tambien vuelven a leerse sin que el registro haya cambiado. Mientras el registro no se reescriba y nada
pise el hueco, la memoria y el registro valen lo mismo, y el `LOAD` es una copia (o nada, si el destino
es el mismo registro). Tambien una carga repetida del mismo hueco: la segunda copia a la primera.

El analisis es el de `forward_must` sobre el CFG: `{desplazamiento: registro que tiene el mismo valor}`,
valido solo si lo es por todos los caminos. Lo que invalida una entrada:
  - el registro se escribe (cualquier instruccion que lo defina, incluidas las llamadas con los
    caller-saved);
  - otro `STORE`/`STOREB`/`STOREH` sobre esa palabra, o con un desplazamiento simbolico de R30;
  - una llamada (`JAL`/`JALR`): el destino puede pisar el area de argumentos y cualquier hueco al que se le
    haya dado la direccion;
  - un store por un puntero, si el hueco esta en o por encima de la direccion de marco mas baja que la
    funcion calcula (`ADDI d, R30, n`); si calcula R30 de otra forma, caen todos;
  - cualquier cambio de R30 (el prologo y el epilogo).
Solo palabras (`LOAD`/`STORE`), con desplazamiento numerico y multiplo de 4. Los huecos que `stackslots`
ya llevo a registros no estan aqui. Los helpers de ABI privada no se tocan.

Las copias que deja se limpian con `copyprop` y `dce`, que van detras."""
from __future__ import annotations

from ..flow import build_cfg, forward_must
from ..isa import STACK, defs_uses, number, reg_of
from ..model import Line, Unit
from ..registry import register_pass

STORES_BY_WIDTH = {"STORE": 4, "STOREB": 1, "STOREH": 2}
EVERYTHING = 1 << 30


def escape_floor(instructions: list[Line]) -> int:
    """El desplazamiento mas bajo cuya direccion calcula la funcion; EVERYTHING si no calcula ninguna, 0 si
    usa R30 de una forma que no se sigue."""
    floor = EVERYTHING
    for line in instructions:
        if line.op in ("JR", "EXIT", "HALT", "TRAP"):
            continue                                        # leen R30 por convenio
        if STACK not in defs_uses(line)[1]:
            continue
        args = line.args
        if (line.op in ("LOAD", "LOADB", "LOADUB", "LOADH", "LOADUH", "STORE", "STOREB", "STOREH")
                and len(args) == 3 and reg_of(args[1]) == STACK and reg_of(args[0]) != STACK):
            continue                                        # acceso al hueco, sin guardar R30
        if line.op == "ADDI" and len(args) == 3 and reg_of(args[1]) == STACK:
            if reg_of(args[0]) == STACK:
                continue                                    # ajuste del marco
            amount = number(args[2])
            floor = min(floor, amount) if amount is not None else 0
            continue
        return 0
    return floor


def make_step(floor: int):
    def step(state: dict[int, int], line: Line) -> None:
        written, _ = defs_uses(line)
        if STACK in written:
            state.clear()
            return
        for register in written:
            for offset in [o for o, r in state.items() if r == register]:
                del state[offset]
        op, args = line.op, line.args
        if op in ("JAL", "JALR"):
            state.clear()
            return
        if op in STORES_BY_WIDTH and len(args) == 3:
            if reg_of(args[1]) != STACK:                    # un store por un puntero
                for offset in [o for o in state if o >= floor]:
                    del state[offset]
                return
            offset = number(args[2])
            if offset is None:
                state.clear()
                return
            if op == "STORE":
                if offset % 4:
                    state.clear()
                    return
                state[offset] = reg_of(args[0])
            else:
                state.pop(offset & ~3, None)
            return
        if op == "LOAD" and len(args) == 3 and reg_of(args[1]) == STACK:
            offset = number(args[2])
            destination = reg_of(args[0])
            if offset is not None and offset % 4 == 0 and destination not in (None, 0, STACK):
                if state.get(offset) is None:               # (si seguia valiendo otro registro, se queda)
                    state[offset] = destination
    return step


def forwarded(line: Line, state: dict[int, int]) -> Line | None | bool:
    """False si `line` no es un `LOAD` reenviable; None si sobra; o la copia que lo sustituye."""
    if line.op != "LOAD" or len(line.args) != 3 or reg_of(line.args[1]) != STACK:
        return False
    offset, destination = number(line.args[2]), reg_of(line.args[0])
    if offset is None or offset % 4 or destination in (None, 0, STACK) or offset not in state:
        return False
    source = state[offset]
    if source == destination:
        return None
    return Line("instr", "", op="ADD", args=[line.args[0], f"R{source}", "R0"])


@register_pass("forward", "LOAD de un hueco de pila cuyo valor ya esta en un registro: copia (o sobra)")
def pass_forward(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        instructions = [line for line in function.body if line.kind == "instr"]
        step = make_step(escape_floor(instructions))
        blocks = build_cfg(function)
        if not blocks:
            continue
        for block, entering in zip(blocks, forward_must(blocks, step)):
            state = dict(entering)
            rewritten: list[Line] = []
            for line in block.lines:
                if line.kind != "instr":
                    rewritten.append(line)
                    continue
                replacement = forwarded(line, state)
                if replacement is False:
                    rewritten.append(line)
                elif replacement is None:
                    stats["forward.removed"] = stats.get("forward.removed", 0) + 1
                else:
                    rewritten.append(replacement)
                    stats["forward.copied"] = stats.get("forward.copied", 0) + 1
                step(state, line)
            block.lines = rewritten
        function.body = [line for block in blocks for line in block.lines]
