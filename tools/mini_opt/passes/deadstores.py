"""Stores a los huecos de argumentos entrantes que nadie lee

    STORE R1, R30, 32        (con un marco de 32 bytes: el hueco de R1 esta en el marco del llamador)

El prologo de lcc vuelca R1..R4 a su hueco y los recarga cuando los necesita. Con `forward` casi todas
esas recargas desaparecen y el `STORE` se queda escribiendo algo que nadie lee. Si lo que hay por
encima del marco (desplazamiento >= n, con `ADDI R30, R30, -n` al entrar) es de la funcion --el area de
parametros del llamador, que el destino puede pisar--, un `STORE` ahi sobra cuando:
  - ninguna instruccion de la funcion lee esa palabra (con ningun ancho);
  - nadie calcula la direccion de esa palabra ni de una anterior en el area (`ADDI d, R30, imm` con
    imm >= n: `va_start`, `&param`);
  - R30 solo cambia con el ajuste canonico del marco, y no se usa de otra forma que no se sepa seguir.

Por debajo del marco no se toca nada: ahi estan el area saliente --que lee el destino de la llamada, aunque
esta funcion no la lea--, los guardados y los locales. Es una condicion de toda la funcion: no necesita
CFG ni liveness. Los helpers de ABI privada no se tocan."""
from __future__ import annotations

from ..isa import LOADS, STACK, STORES, defs_uses, number, reg_of
from ..model import Unit
from ..registry import register_pass
from .tailcalls import frame_size

EVERYTHING = 1 << 30


def analyse(instructions, frame: int):
    """(palabras leidas, direccion de area de parametros mas baja que se calcula), o None si la funcion
    no se puede analizar."""
    loaded: set[int] = set()
    home_floor = EVERYTHING
    for line in instructions:
        written, read = defs_uses(line)
        if STACK in written:
            amount = number(line.args[2]) if len(line.args) == 3 else None
            canonical = (line.op == "ADDI" and len(line.args) == 3 and reg_of(line.args[0]) == STACK
                         and reg_of(line.args[1]) == STACK and amount is not None and abs(amount) == frame)
            if not canonical:
                return None
            continue
        if line.op in ("JR", "EXIT", "HALT", "TRAP") or STACK not in read:
            continue
        args = line.args
        if line.op in LOADS | STORES and len(args) == 3 and reg_of(args[1]) == STACK and reg_of(args[0]) != STACK:
            offset = number(args[2])
            if offset is None:
                return None
            if line.op in LOADS:
                loaded.add(offset & ~3)
            continue
        if line.op == "ADDI" and len(args) == 3 and reg_of(args[1]) == STACK:
            amount = number(args[2])
            if amount is None:
                return None
            if amount >= frame:
                home_floor = min(home_floor, amount)
            continue
        return None
    return loaded, home_floor


@register_pass("deadstores", "STORE a un hueco de argumentos entrantes que nadie lee: se borra")
def pass_deadstores(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        instructions = [line for line in function.body if line.kind == "instr"]
        frame = frame_size(function)
        if frame is None:
            continue
        found = analyse(instructions, frame)
        if found is None:
            continue
        loaded, home_floor = found
        dead = set()
        for line in instructions:
            if line.op != "STORE" or len(line.args) != 3 or reg_of(line.args[1]) != STACK:
                continue
            offset = number(line.args[2])
            if (offset is not None and offset % 4 == 0 and frame <= offset < home_floor
                    and offset not in loaded and reg_of(line.args[0]) != STACK):
                dead.add(id(line))
        if dead:
            function.body = [line for line in function.body if id(line) not in dead]
            stats["deadstores.removed"] = stats.get("deadstores.removed", 0) + len(dead)
