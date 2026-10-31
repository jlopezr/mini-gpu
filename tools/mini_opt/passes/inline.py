"""Expande en linea las llamadas a funciones pequenas de la unidad: `JAL R31, f` -> el cuerpo de `f`.

lcc no expande nada, asi que una funcion de dos lineas (`min2`) cuesta ademas el `JAL`, el `JR` y las
copias de argumentos, y corta los bloques que ven los demas pases. Se expanden las hojas pequenas:

  - definidas en la unidad, de hasta `MAX_INSTRUCTIONS` instrucciones, sin llamadas;
  - que no tocan R30 ni R31 (salvo el `JR R31` de vuelta), sin directivas ni etiquetas de otras funciones en
    medio, y que solo saltan a sus propias etiquetas;
  - que acaban en `JR R31` (no caen a lo que venga detras).

El cuerpo se copia tal cual: con esas condiciones hace lo mismo en el sitio de la llamada que llamado. Solo escribe
registros que el `JAL` ya daba por destruidos (R1..R15) o que restaura antes de volver (un R16..R29 que guarda en
un R1..R15), lee los argumentos donde los deja el llamador y deja el resultado en R1 (y R2). Las etiquetas se
renombran a `L.n` nuevas y cada `JR R31` salta detras de la llamada. La funcion se queda: si nadie mas la nombra,
`deadfuncs` la borra.

Va despues de `deadsaves`, cuando las hojas ya no tienen marco (lcc les pone uno para guardar R29 aunque luego no
haga falta), y antes de los pases que limpian lo que deja (`copyprop`, `dce`, `jumps`...).

`kernelcalls` usa la misma expansion con otra politica: en un kernel se expande TODO, porque es obligatorio, y pronto
(antes de `kernels`):
Un kernel no llama a nada: cada `JAL` de un `__kernel_*` pasa a ser el cuerpo entero de la funcion llamada.

La GPU del simulador funcional (11) y la de la 36 no tienen `JAL` (la 37 si), asi que un kernel escrito con funciones
auxiliares (`min2`, `put`, una primitiva entera...) no se podria ejecutar. Este pase las expande todas, sin limite de
tamano y tambien las que llaman a otras (se expanden a su vez), antes de `kernels`.

El cuerpo se copia tal cual, marco incluido: `JAL` no cambia R30, asi que el `ADDI R30, R30, -n` de la funcion, sus
accesos a la pila (los argumentos 5+ del llamador incluidos) y los guardados de R16..R29 que restaura hacen en el
kernel lo mismo que llamada. Las etiquetas se renombran y cada `JR R31` salta detras de la llamada (`inline`). Como
al final no queda ninguna llamada, nadie lee R31: se borran sus guardados en la pila (`STORE R31` / `LOAD R31`), que
en la GPU son accesos por lane sin coalescer.

Es un error, con el nombre de la funcion, que un kernel llame (directa o indirectamente) a algo que no se puede
expandir: una funcion de otra unidad (`memcpy`...), una recursiva, un helper de ABI privada (`__mini_*`) o una que
salta fuera de si misma o por un puntero (`JALR`).
"""
from __future__ import annotations

import re

from ..isa import BRANCHES, IMM2, LINK, LOADS, R3, STACK, STORES, WRITE_ONLY1, reg_of
from ..model import COMPILER_LOCAL_RE, SYMBOL_RE, Function, Line, OptError, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX

# Medido con mini-gl (40) y la demo de v.tui: con 8 ya entran `min2`, `max2`, `abs2`, `fit`... y casi toda la
# ganancia; con 24 (`put`) la demo ejecuta un 3 % menos pero ocupa un 7 % mas (sin `--whole-program` la funcion
# expandida se queda) y mini-gl casi no gana nada mas.
MAX_INSTRUCTIONS = 8

SIMPLE_OPS = R3 | IMM2 | LOADS | STORES | BRANCHES | WRITE_ONLY1
LABEL_NUMBER_RE = re.compile(r"^L\.(\d+)$")


def expandable(function: Function) -> list[Line] | None:
    """El cuerpo que se copia en cada llamada (sin la etiqueta de la funcion), o None si no se puede expandir."""
    if function.opaque or function.name.startswith(KERNEL_PREFIX):
        return None
    body = function.body[1:]
    labels = {line.name for line in body if line.kind == "label"}
    instructions = [line for line in body if line.kind == "instr"]
    if not instructions or len(instructions) > MAX_INSTRUCTIONS:
        return None
    last = instructions[-1]
    if last.op != "JR" or reg_of(last.args[0]) != LINK:
        return None
    for line in body:
        if line.kind == "directive" or (line.kind == "label" and not COMPILER_LOCAL_RE.match(line.name)):
            return None
        if line.kind != "instr":
            continue
        if line.op == "JR":
            if len(line.args) != 1 or reg_of(line.args[0]) != LINK:
                return None
            continue
        if line.op == "BRA":
            if len(line.args) != 1 or line.args[0] not in labels:
                return None
            continue
        if line.op not in SIMPLE_OPS:
            return None
        if any(reg_of(arg) in (STACK, LINK) for arg in line.args):
            return None
        if line.op in BRANCHES and line.args[-1] not in labels:
            return None
    return body


def fresh_labels(unit: Unit):
    """Numeros de `L.n` que la unidad no usa."""
    used = [int(match.group(1)) for line in unit.lines() if line.kind == "label"
            for match in [LABEL_NUMBER_RE.match(line.name)] if match]
    number = max(used, default=0)
    while True:
        number += 1
        yield f"L.{number}"


def expansion(body: list[Line], labels, call: Line, callee: str) -> list[Line]:
    """El cuerpo con etiquetas nuevas y cada `JR R31` saltando detras; el ultimo cae ahi. Cada linea lleva en
    `origin` la cadena de expansiones (la de la llamada, `callee` y la que ya tuviera)."""
    renamed = {line.name: next(labels) for line in body if line.kind == "label"}
    after = next(labels)

    def rename(arg: str) -> str:
        return SYMBOL_RE.sub(lambda match: renamed.get(match.group(0), match.group(0)), arg)

    last = max(index for index, line in enumerate(body) if line.kind == "instr")
    out: list[Line] = []
    for index, line in enumerate(body):
        origin = (*(call.origin or ()), callee, *(line.origin or ()))
        if line.kind == "label":
            out.append(Line("label", "", name=renamed[line.name], origin=origin))
        elif line.op == "JR":
            if index != last:           # el ultimo (detras solo hay etiquetas) cae detras de la llamada
                out.append(Line("instr", "", op="BRA", args=[after], origin=origin))
        else:
            out.append(Line("instr", "", op=line.op, args=[rename(arg) for arg in line.args], origin=origin))
    out.append(Line("label", "", name=after, origin=call.origin or ()))
    return out


@register_pass("inline", "JAL a una hoja pequena de la unidad -> su cuerpo, con etiquetas nuevas")
def pass_inline(unit: Unit, stats: dict) -> None:
    bodies = {function.name: body for function in unit.functions()
              for body in [expandable(function)] if body is not None}
    if not bodies:
        return
    labels = fresh_labels(unit)
    for function in unit.functions():
        if function.opaque:
            continue
        body: list[Line] = []
        for line in function.body:
            if (line.kind == "instr" and line.op == "JAL" and len(line.args) == 2
                    and reg_of(line.args[0]) == LINK and line.args[1] in bodies and line.args[1] != function.name):
                body += expansion(bodies[line.args[1]], labels, line, line.args[1])
                stats["inline.expanded"] = stats.get("inline.expanded", 0) + 1
            else:
                body.append(line)
        function.body = body


def whole_body(function: Function) -> list[Line] | str:
    """El cuerpo que se copia (sin la etiqueta de la funcion), o por que no se puede."""
    if function.opaque:
        return "es un helper de ABI privada"
    body = function.body[1:]
    labels = {line.name for line in body if line.kind == "label"}
    instructions = [line for line in body if line.kind == "instr"]
    if not instructions or instructions[-1].op != "JR":
        return "no acaba en JR R31"
    for line in body:
        if line.kind == "directive" or (line.kind == "label" and not COMPILER_LOCAL_RE.match(line.name)):
            return f"tiene `{line.render()}` en medio"
        if line.kind != "instr":
            continue
        if line.op == "JR" and (len(line.args) != 1 or reg_of(line.args[0]) != LINK):
            return f"salta por un registro ({line.render()})"
        if line.op == "JALR":
            return f"llama por un puntero ({line.render()})"
        if (line.op == "BRA" or line.op in BRANCHES) and line.args[-1] not in labels:
            return f"salta fuera de si misma ({line.render()})"
    return body


def callees(function: Function) -> list[str]:
    return [line.args[1] for line in function.body
            if line.kind == "instr" and line.op == "JAL" and len(line.args) == 2 and reg_of(line.args[0]) == LINK]


def check_no_recursion(kernel: Function, functions: dict[str, Function], where: str) -> None:
    """Un ciclo de llamadas alcanzable desde el kernel no se puede expandir: error con la cadena."""
    def visit(name: str, chain: list[str]) -> None:
        if name in chain:
            cycle = " -> ".join(chain[chain.index(name):] + [name])
            raise OptError(f"{where}: un kernel no puede llamar a una funcion recursiva ({cycle})")
        function = functions.get(name)
        if function is not None:
            for callee in callees(function):
                visit(callee, chain + [name])
    for callee in callees(kernel):
        visit(callee, [kernel.name])


def drop_link_saves(kernel: Function, stats: dict) -> None:
    """Sin llamadas nadie lee R31: fuera los `STORE R31` / `LOAD R31` de la pila (el retorno pasa a EXIT)."""
    def is_link_save(line: Line) -> bool:
        return (line.kind == "instr" and line.op in ("STORE", "LOAD") and len(line.args) == 3
                and reg_of(line.args[0]) == LINK and reg_of(line.args[1]) == STACK)
    before = len(kernel.body)
    kernel.body = [line for line in kernel.body if not is_link_save(line)]
    if len(kernel.body) != before:
        stats["kernelcalls.link_saves"] = stats.get("kernelcalls.link_saves", 0) + before - len(kernel.body)


@register_pass("kernelcalls", "__kernel_*: cada JAL pasa a ser el cuerpo entero de la funcion (la GPU no tiene JAL)")
def pass_kernelcalls(unit: Unit, stats: dict) -> None:
    functions = {function.name: function for function in unit.functions()}
    kernels = [function for function in unit.functions() if function.name.startswith(KERNEL_PREFIX)]
    if not any(callees(kernel) for kernel in kernels):
        return
    bodies: dict[str, list[Line]] = {}
    labels = fresh_labels(unit)
    for kernel in kernels:
        if not callees(kernel):
            continue
        where = f"{unit.path}: {kernel.name}"
        check_no_recursion(kernel, functions, where)
        while callees(kernel):                  # termina: no hay ciclos
            body: list[Line] = []
            for line in kernel.body:
                if not (line.kind == "instr" and line.op == "JAL" and len(line.args) == 2
                        and reg_of(line.args[0]) == LINK):
                    body.append(line)
                    continue
                name = line.args[1]
                callee = functions.get(name)
                if callee is None:
                    raise OptError(f"{where}: un kernel no puede llamar a {name}: no esta en la unidad "
                                   "(la GPU no tiene JAL)")
                if name not in bodies:
                    found = whole_body(callee)
                    if isinstance(found, str):
                        raise OptError(f"{where}: no se puede expandir {name}, a la que llama: {found}")
                    bodies[name] = found
                body += expansion(bodies[name], labels, line, name)
                stats["kernelcalls.expanded"] = stats.get("kernelcalls.expanded", 0) + 1
            kernel.body = body
        drop_link_saves(kernel, stats)
