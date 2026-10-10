"""Guardados de registros preservados (R16..R29) que la funcion ya no usa

lcc salva en el prologo cada R16..R29 que asigna y los restaura en el epilogo. Despues de `copyprop` y
`dce` hay funciones donde el ultimo uso de uno de esos registros ha desaparecido y el guardado y la
restauracion se quedan: gastan un `STORE` y un `LOAD` por llamada para devolver un valor que nadie
toco. El `.s` de lcc no los tiene (los genera el propio mini-opt al borrar los usos), asi que este pase
es el que cierra esa deuda.

Un registro R16..R29 sobra del guardado si, en toda la funcion, solo aparece en su `STORE` del prologo
y en los `LOAD` que lo restauran desde el mismo hueco. El `JR` y el `EXIT` lo "leen" por convenio (el
llamador espera recibirlo), y eso no cuenta como uso: si la funcion no lo escribe, lo recibe tal cual. Una
llamada tampoco lo toca: es preservado, y el destino tiene que respetarlo.

No hace falta liveness ni CFG. El marco no se encoge (sigue habiendo un hueco sin usar). Los helpers de
ABI privada (`Function.opaque`) no se tocan."""
from __future__ import annotations

from ..isa import CALLEE_SAVED, LOADS, STACK, STORES, defs_uses, number, reg_of
from ..model import Line, Unit
from ..registry import register_pass


def prologue_saves(instructions: list[Line]) -> dict[int, tuple[Line, int]]:
    """{registro: (STORE, desplazamiento)} de los `STORE Rk, R30, off` que siguen al `ADDI R30, R30, -n`."""
    if not instructions:
        return {}
    first = instructions[0]
    if not (first.op == "ADDI" and len(first.args) == 3
            and reg_of(first.args[0]) == STACK and reg_of(first.args[1]) == STACK):
        return {}
    saves: dict[int, tuple[Line, int]] = {}
    for line in instructions[1:]:
        register = reg_of(line.args[0]) if line.args else None
        offset = number(line.args[2]) if len(line.args) == 3 else None
        if (line.op != "STORE" or len(line.args) != 3 or reg_of(line.args[1]) != STACK
                or register not in CALLEE_SAVED or offset is None or register in saves):
            break
        saves[register] = (line, offset)
    return saves


def is_dead_save(register: int, offset: int, store: Line, instructions: list[Line]) -> list[Line] | None:
    """Los `LOAD` que restauran `register` si es un guardado muerto; None si la funcion lo usa o toca su hueco."""
    restores: list[Line] = []
    for line in instructions:
        if line is store or line.op in ("JR", "EXIT"):
            continue
        if line.op in LOADS | STORES and len(line.args) == 3 and reg_of(line.args[1]) == STACK:
            at = number(line.args[2])
            if at is None:
                return None                                 # un desplazamiento simbolico: no se sabe donde cae
            if at == offset:
                if line.op == "LOAD" and reg_of(line.args[0]) == register:
                    restores.append(line)
                    continue
                return None                                 # el hueco se usa para otra cosa
        elif (line.op == "ADDI" and len(line.args) == 3 and reg_of(line.args[1]) == STACK
              and reg_of(line.args[0]) != STACK and number(line.args[2]) == offset):
            return None                                     # la direccion del hueco se calcula
        written, read = defs_uses(line)
        if register in written | read:
            return None
    return restores


@register_pass("deadsaves", "STORE/LOAD de R16..R29 que la funcion no usa: se borran")
def pass_deadsaves(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        instructions = [line for line in function.body if line.kind == "instr"]
        remove: set[int] = set()
        for register, (store, offset) in prologue_saves(instructions).items():
            restores = is_dead_save(register, offset, store, instructions)
            if restores is None:
                continue
            remove.update(id(line) for line in [store, *restores])
            stats["deadsaves.registers"] = stats.get("deadsaves.registers", 0) + 1
        if remove:
            function.body = [line for line in function.body if id(line) not in remove]
