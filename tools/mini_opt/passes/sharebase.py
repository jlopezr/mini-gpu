"""Base compartida para los `LI` con simbolo

lcc carga la direccion de cada campo de una tabla con su propio `LI` (`LI R12, cube_faces+4 ;
LOAD R12, R12, 0`, `LI R11, cube_faces+20 ; LOAD R11, R11, 0`...), y en la preparacion de una fila
del cubo son 24 pares. Con una base en un registro basta el desplazamiento del propio `LOAD`:

    LI R15, cube_faces
    LOAD R12, R15, 4
    LOAD R11, R15, 20

Dentro de un bloque, los `LI simbolo+K` del mismo simbolo cuyo registro solo se lee como base de
cargas y almacenes (y no sale vivo del bloque) se sustituyen por un solo `LI base, simbolo` en un
registro libre durante todo el tramo; los accesos suman K a su desplazamiento. Gana una
instruccion por cada `LI` menos uno (y dos si la direccion no cabe en 16 bits, porque entonces el
`LI` son dos palabras). Si no hay registro libre en el tramo, no hace nada.

Los registros que usa son los mismos que `licm`: R5..R15, R1..R4 y R31 donde la vida de registros
dice que estan libres, y en un kernel tambien R16..R29. Va despues de `licm`, que ya se ha quedado
con los que necesitaba para sacar cosas de los bucles."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..flow import Block, build_cfg, live_after, liveness
from ..isa import LOADS, STORES, defs_uses, instr, number, reg_of
from ..model import Line, Unit
from ..registry import register_pass
from .kernels import KERNEL_PREFIX

SYMBOL_RE = re.compile(r"^([A-Za-z_.$@][A-Za-z0-9_.$@]*)([+-].*)?$")
OFFSET_RANGE = range(-32768, 32768)


def split_address(text: str) -> tuple[str, int] | None:
    """(simbolo, desplazamiento) de `cube_faces+32+12`; None si es un numero o lleva otro simbolo."""
    text = text.strip().replace(" ", "")
    if number(text) is not None:
        return None
    match = SYMBOL_RE.match(text)
    if not match:
        return None
    offset = 0 if match.group(2) is None else number(match.group(2))
    return None if offset is None else (match.group(1), offset)


def is_base_use(line: Line, register: int) -> bool:
    """`LOAD d, register, k` o `STORE v, register, k` con `k` numerico, y el registro solo como base."""
    if line.op not in LOADS | STORES or len(line.args) != 3 or number(line.args[2]) is None:
        return False
    if reg_of(line.args[1]) != register:
        return False
    return line.op in LOADS or reg_of(line.args[0]) != register


@dataclass
class Member:
    position: int                 # indice del `LI` en el bloque
    line: Line
    offset: int                   # la K de simbolo+K
    uses: list[int] = field(default_factory=list)


def base_uses(lines: list[Line], start: int, register: int, live_out: set[int]) -> list[int] | None:
    """Posiciones donde se lee `register` como base hasta que se reescribe; None si se lee de otra forma
    o llega vivo al final del bloque."""
    found: list[int] = []
    for position in range(start + 1, len(lines)):
        line = lines[position]
        if line.kind != "instr":
            continue
        defs, uses = defs_uses(line)
        if register in uses:
            if not is_base_use(line, register):
                return None
            found.append(position)
        if register in defs:
            return found
    return None if register in live_out else found


def candidates(block: Block, live_out: set[int]) -> dict[str, list[Member]]:
    """Los `LI simbolo+K` del bloque que se pueden cambiar, por simbolo."""
    groups: dict[str, list[Member]] = {}
    for position, line in enumerate(block.lines):
        if line.kind != "instr" or line.op != "LI" or len(line.args) != 2:
            continue
        address, register = split_address(line.args[1]), reg_of(line.args[0])
        if address is None or not register:
            continue
        uses = base_uses(block.lines, position, register, live_out)
        if not uses:
            continue
        if any(number(block.lines[u].args[2]) + address[1] not in OFFSET_RANGE for u in uses):
            continue
        groups.setdefault(address[0], []).append(Member(position, line, address[1], uses))
    return groups


def free_register(block: Block, live_out: set[int], first: int, last: int, allowed: list[int]) -> int | None:
    """Un registro de `allowed` que ninguna instruccion del tramo toca y que no esta vivo al acabarlo."""
    mentioned: set[int] = set()
    for line in block.lines[first:last + 1]:
        if line.kind == "instr":
            mentioned |= set().union(*defs_uses(line))
    busy = live_after(block, live_out, last)
    return next((r for r in allowed if r not in mentioned and r not in busy), None)


def share(block: Block, live_out: set[int], allowed: list[int], stats: dict) -> bool:
    """Cambia el grupo con mas `LI` que tenga registro libre. False si no queda ninguno."""
    groups = candidates(block, live_out)
    for symbol, members in sorted(groups.items(), key=lambda item: -len(item[1])):
        if len(members) < 2:
            continue
        first = min(m.position for m in members)
        last = max(max(m.uses) for m in members)
        register = free_register(block, live_out, first, last, allowed)
        if register is None:
            continue
        name = f"R{register}"
        for member in members:
            for use in member.uses:
                line = block.lines[use]
                line.args[1], line.args[2] = name, str(number(line.args[2]) + member.offset)
        dropped = {id(m.line) for m in members}
        lines: list[Line] = []
        for line in block.lines:
            if id(line) in dropped:
                if line is block.lines[first]:
                    lines.append(instr("LI", name, symbol))
                continue
            lines.append(line)
        block.lines = lines
        stats["sharebase.groups"] = stats.get("sharebase.groups", 0) + 1
        stats["sharebase.removed"] = stats.get("sharebase.removed", 0) + len(members)
        return True
    return False


@register_pass("sharebase", "un LI base por simbolo y bloque: los LOAD/STORE suman el desplazamiento")
def pass_sharebase(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        blocks = build_cfg(function)
        if not blocks:
            continue
        kernel = function.name.startswith(KERNEL_PREFIX)
        allowed = list(range(5, 16)) + [1, 2, 3, 4, 31] + (list(range(16, 30)) if kernel else [])
        for block in blocks:
            while share(block, liveness(blocks)[block.index], allowed, stats):
                pass
        function.body = [line for block in blocks for line in block.lines]
