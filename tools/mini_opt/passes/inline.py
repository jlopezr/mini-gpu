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
"""
from __future__ import annotations

import re

from ..isa import BRANCHES, IMM2, LINK, LOADS, R3, STACK, STORES, WRITE_ONLY1, reg_of
from ..model import COMPILER_LOCAL_RE, SYMBOL_RE, Function, Line, Unit
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


def expansion(body: list[Line], labels) -> list[Line]:
    """El cuerpo con etiquetas nuevas y cada `JR R31` saltando detras; el ultimo cae ahi."""
    renamed = {line.name: next(labels) for line in body if line.kind == "label"}
    after = next(labels)

    def rename(arg: str) -> str:
        return SYMBOL_RE.sub(lambda match: renamed.get(match.group(0), match.group(0)), arg)

    last = max(index for index, line in enumerate(body) if line.kind == "instr")
    out: list[Line] = []
    for index, line in enumerate(body):
        if line.kind == "label":
            out.append(Line("label", "", name=renamed[line.name]))
        elif line.op == "JR":
            if index != last:           # el ultimo (detras solo hay etiquetas) cae detras de la llamada
                out.append(Line("instr", "", op="BRA", args=[after]))
        else:
            out.append(Line("instr", "", op=line.op, args=[rename(arg) for arg in line.args]))
    out.append(Line("label", "", name=after))
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
                body += expansion(bodies[line.args[1]], labels)
                stats["inline.expanded"] = stats.get("inline.expanded", 0) + 1
            else:
                body.append(line)
        function.body = body
