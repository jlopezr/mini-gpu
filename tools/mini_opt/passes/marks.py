"""Marca con etiquetas el codigo expandido en linea, para el perfil (`tools/sim_profile.py`).

`inline` y `kernelcalls` copian el cuerpo de una funcion en el sitio de la llamada; despues no queda nada que diga
de donde viene cada instruccion, y el perfil lo atribuye todo a la funcion que llama (en un kernel, todo al kernel).
Las expansiones apuntan en cada linea su origen (`Line.origin`: la cadena de funciones expandidas, de fuera a
dentro) y este pase, el ultimo, pone una etiqueta donde cambia:

    __inl$<unidad>$<funcion>$<n>$primitive.gpu_renderer$segment.gpu_renderer$brush.gpu_renderer
    __inl$<unidad>$<funcion>$<n>                 ; de vuelta en la funcion

Va al final para no partir los bloques que ven los demas pases (una etiqueta corta un bloque basico), y una
etiqueta no ocupa nada: el binario es el mismo. Las lineas que algun pase ha creado de nuevo no traen origen: si
las de antes y despues tienen el mismo, se les da ese; si no, son de la funcion. `<n>` crece en el orden del
codigo, para que el perfil sepa cual vale cuando dos marcas caen en la misma direccion.
"""
from __future__ import annotations

import re
from pathlib import PurePath

from ..model import Line, Unit
from ..registry import register_pass

PREFIX = "__inl$"
UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.]")


def origins(body: list[Line]) -> list[tuple[str, ...]]:
    """El origen de cada instruccion de `body`. Las que ha creado un pase (None) toman el de sus vecinas (la
    anterior y la siguiente que lo tienen) si es el mismo; si no, son de la funcion."""
    known = [line.origin for line in body if line.kind == "instr"]
    result: list[tuple[str, ...]] = [origin or () for origin in known]
    before: tuple[str, ...] | None = None
    index = 0
    while index < len(known):
        if known[index] is not None:
            before = known[index]
            index += 1
            continue
        end = index
        while end < len(known) and known[end] is None:
            end += 1
        after = known[end] if end < len(known) else None
        if before is not None and before == after:
            result[index:end] = [before] * (end - index)
        index = end
    return result


@register_pass("marks", "etiquetas __inl$... donde cambia la funcion expandida en linea (para el perfil)")
def pass_marks(unit: Unit, stats: dict) -> None:
    stem = UNSAFE_RE.sub("_", PurePath(unit.path).stem)
    for function in unit.functions():
        instructions = [line for line in function.body if line.kind == "instr"]
        if not any(line.origin for line in instructions):
            continue
        effective = dict(zip(map(id, instructions), origins(function.body)))
        current: tuple[str, ...] = ()
        number = 0
        body: list[Line] = []
        for line in function.body:
            origin = effective.get(id(line))
            if origin is not None and origin != current:
                number += 1
                name = "$".join([f"{PREFIX}{stem}", function.name, str(number), *origin])
                body.append(Line("label", "", name=name))
                stats["marks"] = stats.get("marks", 0) + 1
                current = origin
            body.append(line)
        function.body = body
