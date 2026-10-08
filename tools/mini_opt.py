#!/usr/bin/env python3
"""Paso entre el `.s` del compilador y `mini-asm`: junta unidades y las transforma.

    mini-link host.s --gpu kernels.s -o programa.s
    mini-asm programa.s -o programa.bin

Cada entrada es una *unidad* con un papel: `cpu` (lo que corre el anfitrion, el
valor por defecto) o `gpu` (kernels). El paso:

  1. lee cada `.s` y lo trocea en funciones, con su grafo de flujo y su vida de
     registros (lo que necesite cualquier transformacion);
  2. aplica a cada unidad los *pases* de su papel (`--list-passes`);
  3. une las unidades en un solo `.s`: una sola `_start` (la de la primera
     unidad `cpu`), un solo `.comm` por simbolo, simbolos externos resueltos
     entre unidades, y error si falta alguno o esta repetido.

El primer pase es `intrinsics`, el equivalente a `threadIdx`/`__syncthreads` de
CUDA sin tocar `rcc`: el C declara `extern volatile int __gpu_tid;` y lo lee
como una variable; el pase convierte el par `LI r,__gpu_tid ; LOAD d,r,0` en
`GETTID d`. Para anadir otro intrinseco basta una entrada en `INTRINSIC_LOADS`
o `INTRINSIC_STORES`; para otra transformacion, una funcion con `@register_pass`.
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
COMPILER_LOCAL_REF_RE = re.compile(r"\bL\.(\d+)\b")
REGISTER_RE = re.compile(r"^R(\d+)$", re.IGNORECASE)
SYMBOL_RE = re.compile(r"[A-Za-z_.$@][A-Za-z0-9_.$@]*")


class LinkError(ValueError):
    """Entrada mala (simbolo repetido, indefinido, intrinseco mal usado...)."""


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
    role: str                       # "cpu" | "gpu"
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


def parse_unit(source: str, path: str = "<entrada>", role: str = "cpu") -> Unit:
    """Trocea el `.s`: una funcion es una etiqueta de `.text` que no es interna de
    lcc (`L.n`), con sus directivas de cabecera (`.globl`, `.align`) y hasta la
    siguiente funcion o el siguiente cambio de seccion. Las directivas de
    cabecera se retienen hasta ver la linea siguiente: si es una funcion, son su
    cabecera; si no, siguen siendo parte de lo que estaba abierto."""
    unit = Unit(path, role)
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


# ---------------------------------------------------------------------------
# Pases
# ---------------------------------------------------------------------------

PASSES: dict[str, tuple[Callable, str]] = {}
DEFAULT_PASSES = {"cpu": [], "gpu": ["intrinsics"]}


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
# Escrituras: `LI r,sim ; STORE v,r,0` => `OP` (el valor se descarta).
INTRINSIC_STORES = {
    "__gpu_bar": "BAR",
}


@register_pass("intrinsics", "variables __gpu_* -> GETTID/GETLANE/GETWARP/GETLWARP/GETARG/BAR")
def pass_intrinsics(unit: Unit, stats: dict) -> None:
    names = set(INTRINSIC_LOADS) | set(INTRINSIC_STORES)
    for function in unit.functions():
        blocks = build_cfg(function)
        live_out = liveness(blocks)
        for block in blocks:
            i = 0
            while i < len(block.lines) - 1:
                a, b = block.lines[i], block.lines[i + 1]
                if (a.kind == "instr" and a.op == "LI" and len(a.args) == 2
                        and a.args[1] in names and b.kind == "instr"):
                    tmp = reg_of(a.args[0])
                    sym = a.args[1]
                    is_load = sym in INTRINSIC_LOADS and b.op == "LOAD"
                    is_store = sym in INTRINSIC_STORES and b.op == "STORE"
                    ok_shape = (len(b.args) == 3 and b.args[2] in ("0", "+0")
                                and reg_of(b.args[1]) == tmp)
                    if not ((is_load or is_store) and ok_shape):
                        raise LinkError(
                            f"{unit.path}: '{sym}' solo se puede leer"
                            f"{' o escribir' if sym in INTRINSIC_STORES else ''} como "
                            f"variable entera ({function.name})")
                    if is_load:
                        dest = reg_of(b.args[0])
                        # el temporal de la direccion no puede seguir vivo
                        if tmp != dest and tmp in live_after(block, live_out[block.index], i + 1):
                            raise LinkError(
                                f"{unit.path}: {function.name}: R{tmp} sigue vivo tras leer {sym}")
                        new = Line("instr", "", op=INTRINSIC_LOADS[sym], args=[b.args[0]])
                    else:
                        if tmp in live_after(block, live_out[block.index], i + 1):
                            raise LinkError(
                                f"{unit.path}: {function.name}: R{tmp} sigue vivo tras escribir {sym}")
                        new = Line("instr", "", op=INTRINSIC_STORES[sym])
                    block.lines[i:i + 2] = [new]
                    stats["intrinsics"] = stats.get("intrinsics", 0) + 1
                else:
                    i += 1
        # volver a montar el cuerpo con los bloques tocados
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
                raise LinkError(
                    f"{unit.path}: {function.name}: uso no soportado de un intrinseco: {line.render()}")


# ---------------------------------------------------------------------------
# Union de unidades
# ---------------------------------------------------------------------------

def defined_symbols(unit: Unit) -> set[str]:
    return {l.name for l in unit.lines() if l.kind == "label"}


def directive_parts(line: Line) -> list[str]:
    return line.text.replace(",", " ").split()


def link(units: list[Unit], allow_undefined: bool = False) -> str:
    """Une las unidades en un `.s`. `_start` solo de la primera `cpu`; `.comm`
    sin repetir; los `.extern` desaparecen (se comprueban); funciones unicas."""
    defined: dict[str, str] = {}
    start_owner = next((u for u in units if u.role == "cpu"), None)
    for unit in units:
        for name in defined_symbols(unit):
            if COMPILER_LOCAL_RE.match(name):
                continue
            if name == "_start" and unit is not start_owner:
                continue
            if name in defined:
                raise LinkError(f"simbolo repetido '{name}' en {defined[name]} y {unit.path}")
            defined[name] = unit.path
    comm: dict[str, tuple[int, str]] = {}
    externs: dict[str, str] = {}
    out: list[str] = []
    for index, unit in enumerate(units):
        # las `L.n` de lcc empiezan en 1 en cada compilacion: sin renombrarlas por
        # unidad, dos `.s` juntos (con `.include` tambien) chocan en `L.2`
        local = lambda text, i=index: COMPILER_LOCAL_REF_RE.sub(lambda m: f"L.{i}.{m.group(1)}", text)
        for chunk in unit.chunks:
            lines = chunk.header + chunk.body if isinstance(chunk, Function) else [chunk]
            if isinstance(chunk, Function) and chunk.name == "_start" and unit is not start_owner:
                continue
            for line in lines:
                if line.kind == "directive":
                    parts = directive_parts(line)
                    word = parts[0].lower()
                    if word == ".extern":
                        externs.setdefault(parts[1], unit.path)
                        continue
                    if word == ".comm":
                        size = int(parts[2], 0)
                        if parts[1] in defined and parts[1] not in comm:
                            raise LinkError(f".comm '{parts[1]}' choca con una definicion en {defined[parts[1]]}")
                        old = comm.get(parts[1], (0, unit.path))
                        comm[parts[1]] = (max(old[0], size), old[1])
                        continue
                out.append(local(line.render()))
    undefined = sorted(s for s in externs if s not in defined and s not in comm)
    if undefined and not allow_undefined:
        raise LinkError("simbolos sin definir: " + ", ".join(
            f"{s} (declarado en {externs[s]})" for s in undefined))
    if comm:
        out.append(".bss")
        out.extend(f".comm {name},{size}" for name, (size, _) in comm.items())
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(inputs: list[tuple[str, str]], passes: dict[str, list[str]] | None = None,
        allow_undefined: bool = False, stats: dict | None = None) -> str:
    """inputs: [(ruta, papel)]. Devuelve el `.s` unido."""
    passes = passes or DEFAULT_PASSES
    stats = stats if stats is not None else {}
    units = []
    for path, role in inputs:
        unit = parse_unit(Path(path).read_text(encoding="utf-8"), path, role)
        for name in passes.get(role, []):
            if name not in PASSES:
                raise LinkError(f"pase desconocido '{name}' (--list-passes)")
            PASSES[name][0](unit, stats)
        units.append(unit)
    return link(units, allow_undefined)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help=".s del anfitrion (papel cpu)")
    parser.add_argument("--cpu", action="append", default=[], metavar="FILE")
    parser.add_argument("--gpu", action="append", default=[], metavar="FILE",
                        help=".s de kernels de la GPU (se les aplican los pases gpu)")
    parser.add_argument("-o", "--output", type=Path, help="`.s` de salida (por defecto stdout)")
    parser.add_argument("--passes-gpu", help="pases de las unidades gpu, separados por coma "
                        f"(por defecto {','.join(DEFAULT_PASSES['gpu']) or 'ninguno'})")
    parser.add_argument("--passes-cpu", help="pases de las unidades cpu (por defecto ninguno)")
    parser.add_argument("--allow-undefined", action="store_true")
    parser.add_argument("--stats", action="store_true", help="resumen de lo que hizo cada pase")
    parser.add_argument("--list-passes", action="store_true")
    args = parser.parse_args(argv)
    if args.list_passes:
        for name, (_, doc) in PASSES.items():
            print(f"{name:12s} {doc}")
        return 0
    inputs = [(f, "cpu") for f in args.files + args.cpu] + [(f, "gpu") for f in args.gpu]
    if not inputs:
        parser.error("hace falta al menos un .s")
    passes = {"cpu": DEFAULT_PASSES["cpu"], "gpu": DEFAULT_PASSES["gpu"]}
    if args.passes_gpu is not None:
        passes["gpu"] = [p for p in args.passes_gpu.split(",") if p]
    if args.passes_cpu is not None:
        passes["cpu"] = [p for p in args.passes_cpu.split(",") if p]
    stats: dict = {}
    try:
        text = run(inputs, passes, args.allow_undefined, stats)
    except LinkError as error:
        print(f"mini-link: {error}", file=sys.stderr)
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
