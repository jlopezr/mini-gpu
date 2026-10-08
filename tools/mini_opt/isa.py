"""Que lee y escribe cada instruccion (`defs_uses`) y los conjuntos de mnemonicos."""
from __future__ import annotations

import re

from .model import Line


REGISTER_RE = re.compile(r"^R(\d+)$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Registros leidos y escritos por instruccion
# ---------------------------------------------------------------------------

R3 = {"ADD", "SUB", "MULFX", "AND", "OR", "XOR", "SHL", "SHR", "SAR", "MUL", "MULHI",
      "DIV", "DIVU", "REM", "REMU", "SLT", "SLTU"}

IMM2 = {"ADDI", "ANDI", "ORI", "XORI", "SHLI", "SHRI", "SARI"}

LOADS = {"LOAD", "LOADB", "LOADUB", "LOADH", "LOADUH"}

STORES = {"STORE", "STOREB", "STOREH"}

BRANCHES = {"BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU"}

GETID = {"GETTID", "GETLANE", "GETWARP", "GETLWARP", "GETARG"}

WRITE_ONLY1 = {"MOVI", "MOVHI", "LI"} | GETID

ARG_REGS = tuple(range(1, 5))

CALLER_SAVED = tuple(range(1, 16))

CALLEE_SAVED = tuple(range(16, 30))

STACK, LINK = 30, 31


def reg_of(arg: str) -> int | None:
    match = REGISTER_RE.match(arg.strip())
    return int(match.group(1)) if match else None


def defs_uses(line: Line) -> tuple[set[int], set[int]]:
    """(escribe, lee) de una instruccion. Una llamada lee los argumentos y
    destruye los caller-saved; un `JR` (retorno) lee lo que el llamador espera."""
    op, args = line.op, line.args
    regs = [reg_of(a) for a in args]
    defs: set[int] = set()
    uses: set[int] = set()
    if op in R3:
        defs.add(regs[0]); uses.update(regs[1:3])
    elif op in IMM2 or op in LOADS:
        defs.add(regs[0]); uses.add(regs[1])
    elif op in WRITE_ONLY1:
        defs.add(regs[0])
    elif op in STORES or op in BRANCHES:
        uses.update(r for r in regs[:2] if r is not None)
    elif op == "JAL":
        defs.update(CALLER_SAVED); defs.add(LINK); defs.add(regs[0] if regs[0] is not None else LINK)
        uses.update(ARG_REGS)
    elif op == "JALR":
        defs.update(CALLER_SAVED); defs.add(LINK)
        uses.update(ARG_REGS); uses.update(r for r in regs if r is not None)
    elif op == "JR":
        uses.update(r for r in regs if r is not None)
        uses.update((1, 2, STACK, *CALLEE_SAVED))
    elif op in ("EXIT", "HALT", "TRAP"):
        uses.update((STACK, *CALLEE_SAVED))
    defs.discard(None); uses.discard(None)
    defs.discard(0); uses.discard(0)        # R0 es la constante cero
    return defs, uses


def number(text: str) -> int | None:
    """Un desplazamiento numerico como los de lcc: `16`, `-8`, `-8+80` (un local mas el tamano del
    marco). None si lleva un nombre (una etiqueta)."""
    parts = re.findall(r"[+-]?[^+-]+", text.strip().replace(" ", ""))
    if not parts or "".join(parts) != text.strip().replace(" ", ""):
        return None
    try:
        return sum(int(part, 0) for part in parts)
    except ValueError:
        return None


def instr(op: str, *args: str) -> Line:
    return Line("instr", "", op=op, args=list(args))


PURE_OPS = (R3 - {"DIV", "DIVU", "REM", "REMU"}) | IMM2 | {"MOVI", "MOVHI", "LI"}


def use_slots(line: Line) -> list[int] | None:
    """Posiciones de los operandos que son registros leidos; None si no se sabe reescribirlos."""
    op = line.op
    if op in R3:
        return [1, 2]
    if op in IMM2 or op in LOADS:
        return [1]
    if op in STORES or op in BRANCHES:
        return [0, 1]
    if op in WRITE_ONLY1:
        return []
    return None
