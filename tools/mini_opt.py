#!/usr/bin/env python3
"""Filtro entre el `.s` del compilador y `mini-asm`: aplica pases a un `.s`.

    mini-lcc --no-crt kernels.c -o kernels.s
    mini-opt kernels.s -o kernels.opt.s --stats
    mini-asm programa.asm -o programa.bin       # con `.include "kernels.opt.s"`

Juntar unidades lo hace el ensamblador con `.include` (y desde que las `L.n` de lcc
son privadas de cada fichero, dos `.s` no chocan); el arranque, `1.isa/runtime/crt0.s`.
Este filtro solo transforma un `.s` en otro: lo trocea en funciones, calcula su grafo de
flujo y la vida de sus registros, y aplica los pases pedidos (`--list-passes`).

El primer pase es `intrinsics`, el equivalente a `threadIdx`/`__syncthreads` de CUDA sin
tocar `rcc`: el C declara `extern volatile int __gpu_tid;` y lo lee como una variable;
el pase convierte el par `LI r,__gpu_tid ; LOAD d,r,0` en `GETTID d`. Para anadir otro
intrinseco basta una entrada en `INTRINSIC_LOADS` o `INTRINSIC_STORES`; para otra
transformacion, una funcion con `@register_pass`.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Modelo del `.s`
# ---------------------------------------------------------------------------

LABEL_RE = re.compile(r"^([A-Za-z_.$@][A-Za-z0-9_.$@]*):\s*(.*)$")
COMPILER_LOCAL_RE = re.compile(r"^L\.\d+$")     # las etiquetas internas de lcc
REGISTER_RE = re.compile(r"^R(\d+)$", re.IGNORECASE)
SYMBOL_RE = re.compile(r"[A-Za-z_.$@][A-Za-z0-9_.$@]*")


class OptError(ValueError):
    """Entrada mala (un intrinseco mal usado...)."""


@dataclass
class Line:
    """Una linea del `.s`: `label`, `instr` o `directive` (todo lo demas)."""
    kind: str
    text: str                       # directiva o instruccion, sin etiqueta
    op: str = ""                    # mnemonico en mayusculas (instr)
    args: list[str] = field(default_factory=list)
    name: str = ""                  # etiqueta (label)

    def render(self) -> str:
        if self.kind == "label":
            return f"{self.name}:"
        if self.kind == "instr":
            return f"{self.op} {', '.join(self.args)}" if self.args else self.op
        return self.text


def parse_line(raw: str) -> list[Line]:
    text = raw.split(";", 1)[0].strip() if '"' not in raw else raw.strip()
    if not text:
        return []
    out: list[Line] = []
    match = LABEL_RE.match(text)
    if match and not text.startswith("."):
        out.append(Line("label", "", name=match.group(1)))
        text = match.group(2).strip()
        if not text:
            return out
    if text.startswith("."):
        out.append(Line("directive", text))
        return out
    op, _, rest = text.partition(" ")
    args = [a.strip() for a in rest.split(",")] if rest.strip() else []
    out.append(Line("instr", text, op=op.upper(), args=args))
    return out


@dataclass
class Function:
    name: str
    header: list[Line]              # `.text`, `.globl f`, `.align 4` que la preceden
    body: list[Line]                # desde la etiqueta de la funcion inclusive


@dataclass
class Unit:
    path: str
    chunks: list = field(default_factory=list)   # Line o Function, en orden

    def functions(self) -> list[Function]:
        return [c for c in self.chunks if isinstance(c, Function)]

    def lines(self) -> list[Line]:
        out: list[Line] = []
        for chunk in self.chunks:
            if isinstance(chunk, Function):
                out += chunk.header + chunk.body
            else:
                out.append(chunk)
        return out


HEADER_DIRECTIVES = (".globl", ".global", ".align")
SECTION_WORDS = (".text", ".code", ".data", ".bss", ".rodata", ".rdata")


def parse_unit(source: str, path: str = "<entrada>") -> Unit:
    """Trocea el `.s`: una funcion es una etiqueta de `.text` que no es interna de
    lcc (`L.n`), con sus directivas de cabecera (`.globl`, `.align`) y hasta la
    siguiente funcion o el siguiente cambio de seccion. Las directivas de
    cabecera se retienen hasta ver la linea siguiente: si es una funcion, son su
    cabecera; si no, siguen siendo parte de lo que estaba abierto."""
    unit = Unit(path)
    section = ".text"
    pending: list[Line] = []
    current: Function | None = None

    def release():
        """Las directivas retenidas no eran cabecera: a donde estaban."""
        target = current.body if current is not None else unit.chunks
        target.extend(pending)
        pending.clear()

    for raw in source.splitlines():
        for line in parse_line(raw):
            word = line.text.split(None, 1)[0].lower() if line.kind == "directive" else ""
            if word in SECTION_WORDS:
                if word in (".text", ".code") and section == ".text":
                    pending.append(line)    # sigue en .text: cabecera de la siguiente
                    continue
                release()
                section = ".text" if word in (".text", ".code") else word
                if section == ".text":
                    pending.append(line)
                else:
                    current = None
                    unit.chunks.append(line)
                continue
            if word in (".extern", ".comm"):
                release()
                current = None          # declaraciones: no son codigo de la funcion
                unit.chunks.append(line)
                continue
            if section == ".text" and word in HEADER_DIRECTIVES:
                pending.append(line)
                continue
            if section == ".text" and line.kind == "label" and not COMPILER_LOCAL_RE.match(line.name):
                current = Function(line.name, list(pending), [line])
                pending.clear()
                unit.chunks.append(current)
                continue
            release()
            if current is not None and section == ".text":
                current.body.append(line)
            else:
                unit.chunks.append(line)
    release()
    return unit


def render_unit(unit: Unit) -> str:
    return "\n".join(line.render() for line in unit.lines()) + "\n"


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


# ---------------------------------------------------------------------------
# Grafo de flujo y vida de registros
# ---------------------------------------------------------------------------

@dataclass
class Block:
    index: int
    lines: list[Line]
    succ: list[int] = field(default_factory=list)


def label_target(line: Line) -> str:
    return line.args[-1]


def build_cfg(function: Function) -> list[Block]:
    """Bloques basicos de una funcion. Salta hacia fuera (a otra funcion) no
    genera arista. `BRA`, `EXIT`, `HALT`, `JR` terminan sin continuar."""
    blocks: list[Block] = []
    current: list[Line] = []
    for line in function.body:
        if line.kind == "label" and current:
            blocks.append(Block(len(blocks), current))
            current = []
        current.append(line)
        if line.kind == "instr" and (line.op in BRANCHES or line.op in
                                     ("BRA", "EXIT", "HALT", "TRAP", "JR")):
            blocks.append(Block(len(blocks), current))
            current = []
    if current:
        blocks.append(Block(len(blocks), current))
    at = {}
    for block in blocks:
        for line in block.lines:
            if line.kind == "label":
                at[line.name] = block.index
    for block in blocks:
        last = next((l for l in reversed(block.lines) if l.kind == "instr"), None)
        falls = last is None or last.op not in ("BRA", "EXIT", "HALT", "TRAP", "JR")
        if last is not None and (last.op in BRANCHES or last.op == "BRA"):
            target = label_target(last)
            if target in at:
                block.succ.append(at[target])
        if falls and block.index + 1 < len(blocks):
            block.succ.append(block.index + 1)
    return blocks


def liveness(blocks: list[Block]) -> list[set[int]]:
    """Registros vivos a la salida de cada bloque (analisis hacia atras)."""
    live_in = [set() for _ in blocks]
    live_out = [set() for _ in blocks]
    changed = True
    while changed:
        changed = False
        for block in reversed(blocks):
            out = set().union(*(live_in[s] for s in block.succ)) if block.succ else set()
            live = set(out)
            for line in reversed(block.lines):
                if line.kind == "instr":
                    defs, uses = defs_uses(line)
                    live = (live - defs) | uses
            if out != live_out[block.index] or live != live_in[block.index]:
                live_out[block.index], live_in[block.index] = out, live
                changed = True
    return live_out


def live_after(block: Block, live_out: set[int], position: int) -> set[int]:
    """Registros vivos justo despues de `block.lines[position]`."""
    live = set(live_out)
    for line in reversed(block.lines[position + 1:]):
        if line.kind == "instr":
            defs, uses = defs_uses(line)
            live = (live - defs) | uses
    return live


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


def free_register(busy: set[int], where: str) -> int:
    """Un temporal de R5..R15 que no este en `busy`. R5 y R6 son los scratch del
    backend (nunca los asigna el compilador), asi que casi siempre hay uno."""
    for r in range(5, 16):
        if r not in busy:
            return r
    raise OptError(f"{where}: no queda ningun registro libre para una expansion")


def live_in_entry(blocks: list[Block], live_out: list[set[int]]) -> set[int]:
    """Registros que la funcion lee antes de escribirlos (vivos a la entrada)."""
    return live_after(Block(-1, [Line("directive", "")] + blocks[0].lines), live_out[0], 0)


# ---------------------------------------------------------------------------
# Pases
# ---------------------------------------------------------------------------

PASSES: dict[str, tuple[Callable, str]] = {}
DEFAULT_PASSES = ["intrinsics", "kernels", "ssy"]


def register_pass(name: str, doc: str):
    def wrap(fn):
        PASSES[name] = (fn, doc)
        return fn
    return wrap


# Variables especiales -> instruccion. `LI r,sim ; LOAD d,r,0` => `OP d`.
INTRINSIC_LOADS = {
    "__gpu_tid": "GETTID",
    "__gpu_lane": "GETLANE",
    "__gpu_warp": "GETWARP",
    "__gpu_lwarp": "GETLWARP",
    "__gpu_arg": "GETARG",
}
# Compuestos: se leen como una variable pero valen mas de una instruccion.
#   __gpu_nthreads = nwarps * nlanes del job, del bloque de argumentos (+0 y +4).
COMPOSITE_LOADS = {"__gpu_nthreads"}
# Escrituras: `LI r,sim ; STORE v,r,0` => `OP` (el valor se descarta).
INTRINSIC_STORES = {
    "__gpu_bar": "BAR",
}


def reaching_symbols(blocks: list[Block], names: set[str]) -> list[dict[int, str]]:
    """Por bloque, que registros contienen a la entrada la direccion de un intrinseco
    (`LI r, __gpu_x`). Solo se conserva lo que llega igual por todos los caminos.
    lcc carga la direccion una vez y la reutiliza para varias lecturas, a veces desde
    otro bloque (antes de un bucle, por ejemplo)."""
    entry: list[dict[int, str] | None] = [None] * len(blocks)
    entry[0] = {}
    changed = True
    while changed:
        changed = False
        for block in blocks:
            if entry[block.index] is None:
                continue
            current = dict(entry[block.index])
            for line in block.lines:
                if line.kind == "instr":
                    defs, _ = defs_uses(line)
                    for d in defs:
                        current.pop(d, None)
                    if line.op == "LI" and len(line.args) == 2 and line.args[1] in names:
                        current[reg_of(line.args[0])] = line.args[1]
            for s in block.succ:
                if entry[s] is None:
                    entry[s] = dict(current)
                    changed = True
                else:
                    merged = {r: sym for r, sym in entry[s].items() if current.get(r) == sym}
                    if merged != entry[s]:
                        entry[s] = merged
                        changed = True
    return [e if e is not None else {} for e in entry]


@register_pass("intrinsics", "variables __gpu_* -> GETTID/GETLANE/GETWARP/GETLWARP/GETARG/BAR")
def pass_intrinsics(unit: Unit, stats: dict) -> None:
    names = set(INTRINSIC_LOADS) | set(INTRINSIC_STORES) | COMPOSITE_LOADS
    for function in unit.functions():
        where = f"{unit.path}: {function.name}"
        blocks = build_cfg(function)
        if not blocks:
            continue
        live_out = liveness(blocks)
        held = reaching_symbols(blocks, names)
        for block in blocks:
            current = dict(held[block.index])
            i = 0
            while i < len(block.lines):
                line = block.lines[i]
                if line.kind != "instr":
                    i += 1
                    continue
                defs, _ = defs_uses(line)
                new = None
                sym = current.get(reg_of(line.args[1])) if line.op in ("LOAD", "STORE") and len(line.args) == 3 \
                    and line.args[2] in ("0", "+0") and reg_of(line.args[1]) is not None else None
                if sym is not None and line.op == "LOAD" and (sym in INTRINSIC_LOADS or sym in COMPOSITE_LOADS):
                    d = line.args[0]
                    if sym in COMPOSITE_LOADS:
                        after = live_after(block, live_out[block.index], i)
                        t = free_register(after | {reg_of(d)}, where)
                        new = [instr("GETARG", d), instr("LOAD", f"R{t}", d, "0"),
                               instr("LOAD", d, d, "4"), instr("MUL", d, d, f"R{t}")]
                    else:
                        new = [instr(INTRINSIC_LOADS[sym], d)]
                elif sym is not None and line.op == "STORE" and sym in INTRINSIC_STORES \
                        and reg_of(line.args[0]) not in current:
                    new = [instr(INTRINSIC_STORES[sym])]
                if new is not None:
                    block.lines[i:i + 1] = new
                    stats["intrinsics"] = stats.get("intrinsics", 0) + 1
                    i += len(new)
                else:
                    i += 1
                for d in defs:
                    current.pop(d, None)
                if line.op == "LI" and len(line.args) == 2 and line.args[1] in names:
                    current[reg_of(line.args[0])] = line.args[1]
        # la direccion cargada ya no la usa nadie: fuera. Si algo mas la usa (se tomo la
        # direccion, se sumo...), no se puede reescribir
        function.body = [line for block in blocks for line in block.lines]
        blocks = build_cfg(function)
        live_out = liveness(blocks)
        for block in blocks:
            i = 0
            while i < len(block.lines):
                line = block.lines[i]
                if line.kind == "instr" and line.op == "LI" and len(line.args) == 2 and line.args[1] in names:
                    register = reg_of(line.args[0])
                    if register in live_after(block, live_out[block.index], i):
                        raise OptError(f"{where}: '{line.args[1]}' solo se puede leer"
                                       f"{' o escribir' if line.args[1] in INTRINSIC_STORES else ''} como "
                                       f"variable entera (R{register} sigue vivo tras leer {line.args[1]})")
                    del block.lines[i]
                    continue
                i += 1
        function.body = [line for block in blocks for line in block.lines]
    # las declaraciones `.extern` de los intrinsecos ya no designan nada
    unit.chunks = [c for c in unit.chunks
                   if not (isinstance(c, Line) and c.kind == "directive"
                           and directive_parts(c)[0].lower() == ".extern"
                           and directive_parts(c)[1] in names)]
    # ninguna referencia suelta a un intrinseco
    for function in unit.functions():
        for line in function.body:
            if line.kind == "instr" and any(a in names for a in line.args):
                raise OptError(
                    f"{unit.path}: {function.name}: uso no soportado de un intrinseco: {line.render()}")


# ---------------------------------------------------------------------------
# Kernels de GPU: `__kernel_<nombre>` es una funcion que arranca una lane
# ---------------------------------------------------------------------------

KERNEL_PREFIX = "__kernel_"
# Bytes de pila por lane y simbolo de la zona; los define el runtime de C (gpu.c) y
# tienen que coincidir con `GPU_STACK_PER_LANE` de gpu.h.
GPU_STACK_PER_LANE = 512
GPU_STACK_SYMBOL = "__gpu_stack"
KERNEL_PARAMS = 4                       # R1..R4, del bloque de argumentos +8, +12, +16, +20
SHIFT_IMMEDIATE = {"SHLI": "SHL", "SHRI": "SHR", "SARI": "SAR"}

# Lo que ejecutan las lanes de la GPU en cada prototipo. `LI` es un pseudo del ensamblador.
GPU_ISAS = {
    "36": {"NOP", "ADD", "SUB", "MULFX", "AND", "OR", "XOR", "SHL", "SHR", "SAR", "MUL", "DIV",
           "MOVI", "ADDI", "ANDI", "ORI", "XORI", "LI", "MOVHI", "LOAD", "STORE", "LOADB",
           "LOADUB", "STOREB", "LOADH", "LOADUH", "STOREH", "BEQ", "BNE", "BLT", "BGE",
           "BLTU", "BGEU", "BRA", "GETTID", "GETLANE", "GETWARP", "GETLWARP", "GETARG",
           "SSY", "BAR", "EXIT", "TRAP", "HALT"},
}
GPU_ISA = "36"


def drop_frame(function: Function, stats: dict) -> bool:
    """Quita de un kernel lo que lcc guarda y restaura de los registros preservados.

    El prologo de lcc (`ADDI R30,R30,-N` y un `STORE Rk,R30,off` por cada R16..R29 que usa) y el
    epilogo que lo deshace (los `LOAD` y el `ADDI R30,R30,N`) devuelven esos registros a quien
    llamo. Un kernel no vuelve a nadie: acaba con EXIT. Siempre se borran esos guardados y
    restauraciones (en la GPU cada uno es un acceso a la pila de la lane, con direcciones
    separadas por lane, es decir sin coalescer). Si tras eso NADA mas toca R30 (ni un local ni un
    derrame), se borra tambien el marco y el kernel no necesita pila.

    Devuelve True si ya no queda ninguna referencia a R30, y False si el kernel usa la pila de
    verdad (y se queda con su marco para los locales)."""
    refs = [l for l in function.body
            if l.kind == "instr" and any(reg_of(a) == STACK for a in l.args)]
    if not refs:
        return True
    first = refs[0]
    if not (first.op == "ADDI" and [a.upper() for a in first.args[:2]] == ["R30", "R30"]
            and (number(first.args[2]) or 0) < 0):
        return False
    size = -number(first.args[2])
    saves: dict[int, int] = {}                  # desplazamiento -> registro preservado
    for line in refs[1:]:
        if line.op != "STORE" or reg_of(line.args[1]) != STACK:
            break
        register, offset = reg_of(line.args[0]), number(line.args[2])
        if (register is None or not 16 <= register <= 29 or offset is None or offset in saves
                or not 0 <= offset < size):
            break
        saves[offset] = register
    remove = list(refs[1:1 + len(saves)])
    for line in refs[1 + len(saves):]:
        if (line.op == "LOAD" and reg_of(line.args[1]) == STACK
                and saves.get(number(line.args[2])) == reg_of(line.args[0])):
            remove.append(line)
    rest = [l for l in refs[1:] if all(l is not r for r in remove)]
    epilogue = [l for l in rest if l.op == "ADDI" and [a.upper() for a in l.args[:2]] == ["R30", "R30"]
                and number(l.args[2]) == size]
    only_frame = len(rest) == len(epilogue)
    if only_frame:
        remove += [first] + epilogue
    if not remove:
        return False
    gone = {id(line) for line in remove}
    function.body = [line for line in function.body if id(line) not in gone]
    stats["kernels.frames" if only_frame else "kernels.saves"] = \
        stats.get("kernels.frames" if only_frame else "kernels.saves", 0) + 1
    return only_frame


@register_pass("kernels", "__kernel_*: desplazamientos con registro, ISA de la GPU, entrada (pila de "
                          "lane y parametros desde GETARG) y EXIT en vez de JR R31")
def pass_kernels(unit: Unit, stats: dict) -> None:
    allowed = GPU_ISAS[GPU_ISA]
    for function in unit.functions():
        if not function.name.startswith(KERNEL_PREFIX):
            continue
        where = f"{unit.path}: {function.name}"
        # el retorno de un kernel es parar la lane
        for line in function.body:
            if line.kind == "instr" and line.op == "JR" and [a.upper() for a in line.args] == ["R31"]:
                line.op, line.args = "EXIT", []
        blocks = build_cfg(function)
        live_out = liveness(blocks)
        # desplazamientos con cantidad inmediata: la GPU solo los tiene con registro
        for block in blocks:
            i = 0
            while i < len(block.lines):
                line = block.lines[i]
                if line.kind == "instr" and line.op in SHIFT_IMMEDIATE:
                    d, a, k = line.args
                    busy = live_after(block, live_out[block.index], i) | {reg_of(d), reg_of(a)}
                    t = free_register(busy, where)
                    block.lines[i:i + 1] = [instr("MOVI", f"R{t}", k),
                                            instr(SHIFT_IMMEDIATE[line.op], d, a, f"R{t}")]
                    stats["kernels.shifts"] = stats.get("kernels.shifts", 0) + 1
                    i += 2
                else:
                    i += 1
        function.body = [line for block in blocks for line in block.lines]
        for line in function.body:
            if line.kind == "instr" and line.op not in allowed:
                raise OptError(f"{where}: la GPU del prototipo {GPU_ISA} no ejecuta {line.op} "
                               f"({line.render()})")
        # parametros: R1..R4 que el cuerpo lee antes de escribir. Mas de cuatro irian a la
        # pila del llamador, que un kernel no tiene.
        frame = 0
        for line in function.body:
            if line.kind == "instr" and line.op == "ADDI" and [a.upper() for a in line.args[:2]] == ["R30", "R30"]:
                frame = -(number(line.args[2]) or 0)
                break
        for line in function.body:
            if (line.kind == "instr" and line.op in LOADS and reg_of(line.args[1]) == STACK
                    and (number(line.args[2]) or 0) >= frame > 0):
                raise OptError(f"{where}: un kernel admite {KERNEL_PARAMS} parametros como maximo "
                               "(pasa un puntero a una estructura)")
        uses_stack = not drop_frame(function, stats)
        blocks = build_cfg(function)
        live_out = liveness(blocks)
        params = sorted(r for r in live_in_entry(blocks, live_out) if r in ARG_REGS)
        size = GPU_STACK_PER_LANE
        # la pila de la lane solo se fija si el kernel la usa de verdad
        entry = ([instr("GETTID", "R5"), instr("MOVI", "R6", str(size)), instr("MUL", "R5", "R5", "R6"),
                  instr("LI", "R30", f"{GPU_STACK_SYMBOL}+{size}"), instr("ADD", "R30", "R30", "R5")]
                 if uses_stack else [])
        if params:
            entry.append(instr("GETARG", "R5"))
            entry += [instr("LOAD", f"R{r}", "R5", str(8 + 4 * (r - 1))) for r in params]
        function.body[1:1] = entry              # justo despues de la etiqueta de la funcion
        stats["kernels"] = stats.get("kernels", 0) + 1


# ---------------------------------------------------------------------------
# SSY automatico: donde reconvergen los caminos de un salto divergente
#
# Un salto condicional cuyas lanes toman caminos distintos necesita una region
# abierta con `SSY join` (isa.md): sin ella el SM para con ERROR_SIMT. `join` es el
# postdominador inmediato del salto, el primer punto por el que pasan todos los
# caminos. En un bucle cuyas lanes salen en vueltas distintas, la region se abre
# una vez antes del bucle (en el preheader), con el punto de salida como join; asi
# valen tanto el salto de vuelta como cualquier `break`.
#
# Solo hace falta para los saltos que PUEDEN divergir. Un valor varia entre lanes si
# viene de GETTID o GETLANE (o de una pila, que es de cada lane) y se propaga por la
# aritmetica y las cargas; lo que se define bajo un salto divergente tambien varia.
# Con `SSY_ALL` se trata todo salto condicional como divergente.
# ---------------------------------------------------------------------------

SSY_ALL = False
VARYING_SOURCES = {"GETTID", "GETLANE"}
UNIFORM_SOURCES = {"MOVI", "MOVHI", "LI", "GETWARP", "GETLWARP", "GETARG"}


def postdominators(blocks: list[Block]) -> list[set[int]]:
    """pdom[b] = bloques que estan en todo camino de b a la salida (incluido b). El
    indice len(blocks) es la salida virtual."""
    n = len(blocks)
    pdom = [set(range(n + 1)) for _ in range(n)] + [{n}]
    changed = True
    while changed:
        changed = False
        for b in reversed(range(n)):
            succ = blocks[b].succ or [n]
            new = set.intersection(*(pdom[s] for s in succ)) | {b}
            if new != pdom[b]:
                pdom[b], changed = new, True
    return pdom


def immediate_postdominator(pdom: list[set[int]], b: int) -> int:
    strict = pdom[b] - {b}
    return max(strict, key=lambda p: len(pdom[p]))     # la cadena de postdominadores: el mas cercano


def dominators(blocks: list[Block]) -> list[set[int]]:
    n = len(blocks)
    dom = [set(range(n)) for _ in range(n)]
    dom[0] = {0}
    preds: list[list[int]] = [[] for _ in range(n)]
    for block in blocks:
        for s in block.succ:
            preds[s].append(block.index)
    changed = True
    while changed:
        changed = False
        for b in range(1, n):
            if not preds[b]:
                continue
            new = set.intersection(*(dom[p] for p in preds[b])) | {b}
            if new != dom[b]:
                dom[b], changed = new, True
    return dom


def natural_loops(blocks: list[Block], dom: list[set[int]]) -> dict[int, set[int]]:
    """cabecera -> cuerpo, uniendo los bucles que comparten cabecera."""
    preds: list[list[int]] = [[] for _ in blocks]
    for block in blocks:
        for s in block.succ:
            preds[s].append(block.index)
    loops: dict[int, set[int]] = {}
    for block in blocks:
        for h in block.succ:
            if h in dom[block.index]:                       # arista de vuelta u -> h
                body = loops.setdefault(h, {h})
                stack = [block.index]
                while stack:
                    x = stack.pop()
                    if x not in body:
                        body.add(x)
                        stack.extend(preds[x])
    return loops


def divergent_branches(blocks: list[Block], pdom: list[set[int]]) -> set[int]:
    """Indices de los bloques cuyo salto condicional puede divergir."""
    n = len(blocks)
    last = {b.index: next((l for l in reversed(b.lines) if l.kind == "instr"), None) for b in blocks}
    conditional = {i for i, l in last.items() if l is not None and l.op in BRANCHES}
    if SSY_ALL:
        return conditional
    tainted: set[int] = set()
    while True:
        var_in = [set() for _ in range(n)]
        changed = True
        while changed:
            changed = False
            for block in blocks:
                var = set(var_in[block.index])
                for line in block.lines:
                    if line.kind != "instr":
                        continue
                    defs, uses = defs_uses(line)
                    if not defs:
                        continue
                    if line.op in VARYING_SOURCES or block.index in tainted:
                        varying = True
                    elif line.op in UNIFORM_SOURCES:
                        varying = False
                    elif line.op in LOADS:
                        base = reg_of(line.args[1])
                        varying = base == STACK or base in var       # direccion distinta = dato distinto
                    else:
                        varying = bool(uses & var)
                    var = (var | defs) if varying else (var - defs)
                for s in block.succ:
                    if not var <= var_in[s]:
                        var_in[s] |= var
                        changed = True
        found: set[int] = set()
        for block in blocks:
            if block.index not in conditional:
                continue
            var = set(var_in[block.index])
            for line in block.lines[:-1]:
                if line.kind == "instr":
                    defs, uses = defs_uses(line)
                    if line.op in VARYING_SOURCES or block.index in tainted:
                        v = True
                    elif line.op in UNIFORM_SOURCES:
                        v = False
                    elif line.op in LOADS:
                        v = reg_of(line.args[1]) == STACK or reg_of(line.args[1]) in var
                    else:
                        v = bool(uses & var)
                    if defs:
                        var = (var | defs) if v else (var - defs)
            branch = last[block.index]
            if any(reg_of(a) in var for a in branch.args[:2] if reg_of(a) is not None):
                found.add(block.index)
        # lo que se ejecuta bajo un salto divergente es de unas lanes y no de otras
        region: set[int] = set()
        for b in found:
            join = immediate_postdominator(pdom, b)
            stack = list(blocks[b].succ)
            while stack:
                x = stack.pop()
                if x == join or x in region:
                    continue
                region.add(x)
                stack.extend(blocks[x].succ)
        if region <= tainted:
            return found
        tainted |= region


@register_pass("ssy", "SSY delante de los saltos que pueden divergir (en bucles, antes del bucle)")
def pass_ssy(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if not function.name.startswith(KERNEL_PREFIX):
            continue
        where = f"{unit.path}: {function.name}"
        blocks = build_cfg(function)
        if not blocks:
            continue
        pdom = postdominators(blocks)
        dom = dominators(blocks)
        div = divergent_branches(blocks, pdom)
        if not div:
            continue
        count = [0]

        def label_of(index: int) -> str:
            block = blocks[index]
            if block.lines and block.lines[0].kind == "label":
                return block.lines[0].name
            count[0] += 1
            name = f"__ssy_{function.name}_{count[0]}"
            block.lines.insert(0, Line("label", "", name=name))
            return name

        def common_postdominator(targets: list[int]) -> int:
            common = set.intersection(*(pdom[t] for t in targets))
            if not common:
                raise OptError(f"{where}: no encuentro donde reconvergen las salidas de un bucle")
            return max(common, key=lambda p: len(pdom[p]))

        handled: set[int] = set()
        edits: list[tuple[Block, int | None, int]] = []       # (bloque, posicion o None=al final, join)
        preds: list[list[int]] = [[] for _ in blocks]
        for block in blocks:
            for s in block.succ:
                preds[s].append(block.index)
        for header, body in sorted(natural_loops(blocks, dom).items()):
            exits = [b for b in body if b in div and any(s not in body for s in blocks[b].succ)]
            if not exits:
                continue
            targets = sorted({s for b in exits for s in blocks[b].succ if s not in body})
            join = targets[0] if len(targets) == 1 else common_postdominator(targets)
            for b in exits:
                if immediate_postdominator(pdom, b) == join:
                    handled.add(b)
            if not any(b in handled for b in exits):
                continue
            for p in preds[header]:
                if p in body:
                    continue
                term = next((l for l in reversed(blocks[p].lines) if l.kind == "instr"), None)
                pos = None
                if term is not None and term.op == "BRA":
                    pos = max(i for i, l in enumerate(blocks[p].lines) if l is term)
                elif term is not None and (term.op in BRANCHES or term.op in ("EXIT", "HALT", "JR")):
                    raise OptError(f"{where}: la entrada a un bucle con divergencia sale de un salto "
                                   "condicional; no se sabe donde abrir su region")
                edits.append((blocks[p], pos, join))
        for b in sorted(div - handled):
            join = immediate_postdominator(pdom, b)
            if join >= len(blocks):
                raise OptError(f"{where}: un salto divergente no reconverge antes de salir del kernel")
            edits.append((blocks[b], len(blocks[b].lines) - 1, join))
        # los `SSY` se anaden de atras adelante para no mover las posiciones pendientes
        for block, pos, join in sorted(edits, key=lambda e: (e[0].index, -1 if e[1] is None else e[1]),
                                       reverse=True):
            ssy = instr("SSY", label_of(join))
            if pos is None:
                block.lines.append(ssy)
            else:
                block.lines.insert(pos, ssy)
            stats["ssy"] = stats.get("ssy", 0) + 1
        function.body = [line for block in blocks for line in block.lines]


def directive_parts(line: Line) -> list[str]:
    return line.text.replace(",", " ").split()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def optimize(source: str, passes: list[str] | None = None, path: str = "<entrada>",
             stats: dict | None = None) -> str:
    """Aplica los pases (por defecto `DEFAULT_PASSES`) a un `.s` y devuelve el nuevo."""
    passes = DEFAULT_PASSES if passes is None else passes
    stats = stats if stats is not None else {}
    unit = parse_unit(source, path)
    for name in passes:
        if name not in PASSES:
            raise OptError(f"pase desconocido '{name}' (--list-passes)")
        PASSES[name][0](unit, stats)
    return render_unit(unit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", nargs="?", type=Path, help=".s de entrada")
    parser.add_argument("-o", "--output", type=Path, help="`.s` de salida (por defecto stdout)")
    parser.add_argument("--passes", help="pases separados por coma, en orden "
                        f"(por defecto {','.join(DEFAULT_PASSES)}; vacio = ninguno)")
    parser.add_argument("--ssy-all", action="store_true",
                        help="pase ssy: tratar todo salto condicional como divergente")
    parser.add_argument("--stats", action="store_true", help="resumen de lo que hizo cada pase")
    parser.add_argument("--list-passes", action="store_true")
    args = parser.parse_args(argv)
    if args.list_passes:
        for name, (_, doc) in PASSES.items():
            print(f"{name:12s} {doc}")
        return 0
    if args.input is None:
        parser.error("hace falta un .s de entrada")
    passes = None if args.passes is None else [p for p in args.passes.split(",") if p]
    global SSY_ALL
    SSY_ALL = args.ssy_all
    stats: dict = {}
    try:
        text = optimize(args.input.read_text(encoding="utf-8"), passes, str(args.input), stats)
    except OptError as error:
        print(f"mini-opt: {error}", file=sys.stderr)
        return 1
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.stats:
        print("pases:", stats or "nada que hacer", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
