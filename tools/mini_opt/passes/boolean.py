"""Booleano como valor: un `Bcc` que decide entre cargar 1 y cargar 0 pasa a `SLT`/`SLTU`

    Bcc a,b,Lf ; MOVI r,v1 ; BRA Le ; Lf: ; <r = v2> ; Le:        (v1 y v2 son 0 y 1)

lcc evalua `x = a < b` y `return a == b` con un salto sobre dos cargas de constante, porque su IR
no tiene «set on compare». `SLT` y `SLTU` dan el 0/1 directamente (la ISA no tiene forma con
inmediato, solo `Rd, Ra, Rb`):

    condicion       r = condicion               r = !condicion
    BLT / BLTU      SLT[U] r,a,b                SLT[U] r,a,b ; XORI r,r,1
    BGE / BGEU      SLT[U] r,a,b ; XORI r,r,1   SLT[U] r,a,b
    BEQ             SUB r,a,b ; SLTU r,R0,r ; XORI r,r,1       (con R0 de operando no hace falta el SUB)
    BNE             SUB r,a,b ; SLTU r,R0,r     SUB r,a,b ; SLTU r,R0,r ; XORI r,r,1

No hace falta liveness: `r` se escribe por los dos caminos antes y despues, y la secuencia nueva no
toca nada mas. `r` puede ser un operando (cada instruccion lee antes de escribir). `Lf` se borra
solo si nadie mas salta a ella; `Le` y cualquier otra etiqueta de ese punto se quedan donde estaban."""
from __future__ import annotations

from collections import Counter

from ..isa import BRANCHES, reg_of
from ..model import SYMBOL_RE, Line, Unit
from ..registry import register_pass
from .constprop import constant_of

COMPARE = {"BLT": "SLT", "BGE": "SLT", "BLTU": "SLTU", "BGEU": "SLTU"}

# Lo que da la secuencia base (sin el XORI): True = la condicion del branch, False = su negacion.
BASE_IS_CONDITION = {"BLT": True, "BLTU": True, "BGE": False, "BGEU": False, "BEQ": False, "BNE": True}


def instr(op: str, *args: str) -> Line:
    return Line("instr", "", op=op, args=list(args))


def boolean_set(line: Line) -> tuple[int, int] | None:
    """(registro, 0 o 1) si `line` carga un 0 o un 1 en un registro."""
    if line.kind != "instr" or not line.args or reg_of(line.args[0]) in (None, 0):
        return None
    if line.op == "ADD" and len(line.args) == 3 and reg_of(line.args[1]) == 0 and reg_of(line.args[2]) == 0:
        return reg_of(line.args[0]), 0
    value = constant_of(line)
    if value in (0, 1):
        return reg_of(line.args[0]), value
    return None


def sequence(branch: Line, dest: str, taken_value: int) -> list[Line]:
    """Las instrucciones que dejan en `dest` el valor que daba el original: `taken_value` (0 o 1) si la
    rama se toma y el otro si no. Con `taken_value` = 1 es la condicion del branch; con 0, su negacion."""
    a, b = branch.args[0].strip(), branch.args[1].strip()
    if branch.op in COMPARE:
        out = [instr(COMPARE[branch.op], dest, a, b)]       # a < b
    elif reg_of(a) == 0:                                    # BEQ / BNE: a != b
        out = [instr("SLTU", dest, "R0", b)]
    elif reg_of(b) == 0:
        out = [instr("SLTU", dest, "R0", a)]
    else:
        out = [instr("SUB", dest, a, b), instr("SLTU", dest, "R0", dest)]
    if (taken_value == 1) != BASE_IS_CONDITION[branch.op]:
        out.append(instr("XORI", dest, dest, "1"))
    return out


@register_pass("boolean", "Bcc ; MOVI r,1 ; BRA ; Lf: ; r=0 ; Le: -> SLT/SLTU (+ XORI)")
def pass_boolean(unit: Unit, stats: dict) -> None:
    references: Counter = Counter()
    for line in unit.lines():
        if line.kind == "instr":
            references.update(arg.strip() for arg in line.args)
        elif line.kind == "directive":
            references.update(SYMBOL_RE.findall(line.text))
    for function in unit.functions():
        if function.opaque:
            continue
        body = function.body
        result: list[Line] = []
        i = 0
        while i < len(body):
            line = body[i]
            if (line.kind == "instr" and line.op in BRANCHES and len(line.args) == 3
                    and i + 5 < len(body)):
                taken, jump, lf, other = body[i + 1], body[i + 2], body[i + 3], body[i + 4]
                fallthrough = boolean_set(taken)
                done = boolean_set(other)
                if (fallthrough is not None and done is not None
                        and fallthrough[0] == done[0] and fallthrough[1] != done[1]
                        and jump.kind == "instr" and jump.op == "BRA" and len(jump.args) == 1
                        and lf.kind == "label" and lf.name == line.args[-1]
                        and reg_of(line.args[0]) is not None and reg_of(line.args[1]) is not None):
                    j = i + 5
                    following = []
                    while j < len(body) and body[j].kind == "label":
                        following.append(body[j].name)
                        j += 1
                    if jump.args[0] in following and references[lf.name] == 1:
                        dest = f"R{fallthrough[0]}"
                        result.extend(sequence(line, dest, done[1]))    # tomada: Lf deja `done[1]`
                        stats["boolean.converted"] = stats.get("boolean.converted", 0) + 1
                        i += 5                          # el label Lf desaparece; Le y las demas siguen
                        continue
            result.append(line)
            i += 1
        function.body = result
