"""Rama invertida: `Bcc a,b,L1 ; BRA L2 ; L1:` -> `B!cc a,b,L2 ; L1:`

lcc genera `if (c) return;` y similares con un salto condicional sobre un `BRA`. El mismo camino
se escribe con una sola instruccion: la condicion contraria salta directamente a `L2` y, si no
salta, cae en `L1`. `L1` se queda (puede tener otras referencias). El CFG es el mismo: los dos
destinos y quien llega a cada uno no cambian, solo cual de los dos es el que cae.

Un branch condicional lleva un desplazamiento de 16 bits (+-128 KiB) y `BRA` uno de 26, asi que
solo se invierte cuando `L2` es una etiqueta de la misma funcion y la funcion es pequena."""
from __future__ import annotations

from ..model import Line, Unit
from ..registry import register_pass

OPPOSITE = {"BEQ": "BNE", "BNE": "BEQ", "BLT": "BGE", "BGE": "BLT", "BLTU": "BGEU", "BGEU": "BLTU"}

# 16 bits con signo en palabras: 32768 hacia cada lado. Con menos instrucciones que eso en la
# funcion, cualquier etiqueta de dentro alcanza.
MAX_INSTRUCTIONS = 32000


@register_pass("invert", "Bcc a,b,L1 ; BRA L2 ; L1: -> B!cc a,b,L2 ; L1:")
def pass_invert(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        body = function.body
        if sum(1 for line in body if line.kind == "instr") > MAX_INSTRUCTIONS:
            continue
        labels = {line.name for line in body if line.kind == "label"}
        result: list[Line] = []
        i = 0
        while i < len(body):
            line = body[i]
            jump = body[i + 1] if i + 1 < len(body) else None
            if (line.kind == "instr" and line.op in OPPOSITE and len(line.args) == 3
                    and jump is not None and jump.kind == "instr" and jump.op == "BRA"
                    and len(jump.args) == 1):
                following = set()
                j = i + 2
                while j < len(body) and body[j].kind == "label":
                    following.add(body[j].name)
                    j += 1
                skipped, target = line.args[-1], jump.args[0]
                if skipped in following and target not in following and target in labels:
                    result.append(Line("instr", "", op=OPPOSITE[line.op],
                                       args=[line.args[0], line.args[1], target]))
                    stats["invert.inverted"] = stats.get("invert.inverted", 0) + 1
                    i += 2
                    continue
            result.append(line)
            i += 1
        function.body = result
