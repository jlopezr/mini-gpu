"""Convierte llamadas directas en posicion de cola en saltos, de forma conservadora.

Solo se acepta el epilogo canonico de LCC y un destino definido en la misma
unidad que no recibe argumentos por pila. Asi se puede restaurar el frame del
llamador antes del `BRA` sin tener que recolocar argumentos 5+. Ni el llamador
ni el destino pueden calcular direcciones de su propio frame (`takes_frame_address`):
adonde van no se sabe, y con el frame ya cerrado el destino podria pisarlas.
"""
from __future__ import annotations

from ..isa import CALLEE_SAVED, LOADS, LINK, STACK, STORES, defs_uses, number, reg_of
from ..model import Function, Line, Unit
from ..registry import register_pass


def instruction_lines(function: Function) -> list[Line]:
    return [line for line in function.body if line.kind == "instr"]


def frame_size(function: Function) -> int | None:
    """Tamano del frame canonico, 0 para una funcion sin ajuste de pila."""
    instructions = instruction_lines(function)
    if not instructions:
        return None
    first = instructions[0]
    if (first.op == "ADDI" and len(first.args) == 3
            and reg_of(first.args[0]) == STACK and reg_of(first.args[1]) == STACK):
        amount = number(first.args[2])
        if amount is not None and amount < 0:
            return -amount
    return 0


def takes_frame_address(function: Function) -> bool:
    """La funcion usa R30 de otra forma que como base de un LOAD/STORE o en el ajuste del marco
    (`ADDI R30, R30, n`): calcula la direccion de algo de su frame, o guarda el propio R30.

    Esa direccion puede acabar en cualquier sitio (un registro de argumento, una global, otro objeto):
    si despues se libera el frame para hacer un salto de cola, el destino la lee con el frame cerrado y su
    propio frame puede solapar el hueco. Sin tipos ni metadatos no se sigue a donde va, asi que se rechaza
    la funcion entera, tanto como origen de un salto de cola como destino."""
    for line in instruction_lines(function):
        if line.op in ("JR", "EXIT", "HALT", "TRAP"):
            continue                                    # leen R30 por convenio, no por una direccion
        if STACK not in defs_uses(line)[1]:
            continue
        if (line.op in LOADS | STORES and len(line.args) == 3 and reg_of(line.args[1]) == STACK
                and reg_of(line.args[0]) != STACK):
            continue                                    # acceso a un hueco; STORE R30, ... guarda el propio R30
        if (line.op == "ADDI" and len(line.args) == 3 and reg_of(line.args[0]) == STACK
                and reg_of(line.args[1]) == STACK):
            continue                                    # ajuste del marco
        return True
    return False


def has_stack_arguments(function: Function) -> bool:
    """Detecta lecturas o toma de direccion de argumentos 5+ de MiniABI."""
    size = frame_size(function)
    if size is None:
        return True
    first_stack_argument = size + 16
    for line in instruction_lines(function):
        if (line.op in LOADS and len(line.args) == 3 and reg_of(line.args[1]) == STACK):
            offset = number(line.args[2])
            if offset is not None and offset >= first_stack_argument:
                return True
    # `va_start` y agregados pueden tomar la direccion y cargar de forma indirecta.
    return takes_frame_address(function)


def saved_by_prologue(function: Function) -> set[tuple[int, int]]:
    """Registros/offsets salvados por el prologo canonico de LCC."""
    instructions = instruction_lines(function)
    saved: set[tuple[int, int]] = set()
    for line in instructions[1:]:
        if (line.op != "STORE" or len(line.args) != 3 or reg_of(line.args[1]) != STACK
                or reg_of(line.args[0]) not in (*CALLEE_SAVED, LINK)):
            break
        offset = number(line.args[2])
        if offset is None:
            break
        saved.add((reg_of(line.args[0]), offset))
    return saved


def canonical_epilogue(function: Function, call_index: int) -> list[Line] | None:
    """Devuelve las restauraciones que deben duplicarse antes del tail jump."""
    body = function.body
    size = frame_size(function)
    saved = saved_by_prologue(function)
    if not size or not any(register == LINK for register, _ in saved):
        return None
    movable: list[Line] = []
    saw_link = False
    saw_stack = False
    position = call_index + 1
    while position < len(body):
        line = body[position]
        if line.kind == "label":
            position += 1
            continue
        if line.kind != "instr":
            return None
        if (line.op in LOADS and len(line.args) == 3 and reg_of(line.args[1]) == STACK
                and reg_of(line.args[0]) in (*CALLEE_SAVED, LINK)):
            destination = reg_of(line.args[0])
            offset = number(line.args[2])
            if offset is None or (destination, offset) not in saved:
                return None
            if destination == LINK:
                saw_link = True
            movable.append(line)
            position += 1
            continue
        if (line.op == "ADDI" and len(line.args) == 3
                and reg_of(line.args[0]) == STACK and reg_of(line.args[1]) == STACK
                and number(line.args[2]) == size):
            movable.append(line)
            saw_stack = True
            position += 1
            continue
        if (line.op == "JR" and len(line.args) == 1 and reg_of(line.args[0]) == LINK
                and saw_link and saw_stack):
            return movable
        return None
    return None


@register_pass("tailcalls", "JAL directo en posicion final -> restaura el frame y BRA")
def pass_tailcalls(unit: Unit, stats: dict) -> None:
    functions = {function.name: function for function in unit.functions()}
    safe_targets = {
        name for name, function in functions.items()
        if not function.opaque and not has_stack_arguments(function)
    }
    for function in functions.values():
        if function.opaque or takes_frame_address(function):
            continue
        body = function.body
        for index, line in enumerate(body):
            if (line.kind != "instr" or line.op != "JAL" or len(line.args) != 2
                    or reg_of(line.args[0]) != LINK or line.args[1] not in safe_targets):
                continue
            movable = canonical_epilogue(function, index)
            if movable is None:
                continue
            replacement = [*movable, Line("instr", "", op="BRA", args=[line.args[1]])]
            function.body = body[:index] + replacement + body[index + 1:]
            stats["tailcalls"] = stats.get("tailcalls", 0) + 1
            break
