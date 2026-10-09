"""El `.s` troceado: lineas, funciones y unidades (`parse_unit` / `render_unit`)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LABEL_RE = re.compile(r"^([A-Za-z_.$@][A-Za-z0-9_.$@]*):\s*(.*)$")

# `runtime/gen_softfloat.py` renombra las `L.n` de los bloques embebidos a
# `__sf.n` para que no choquen con las del programa. Siguen siendo etiquetas de
# bloque, no comienzos de funcion: separarlas rompe el CFG y permite que DCE
# borre los valores que llegan a esos bloques.
COMPILER_LOCAL_RE = re.compile(r"^(?:L|__sf)\.\d+$|^@")

SYMBOL_RE = re.compile(r"[A-Za-z_.$@][A-Za-z0-9_.$@]*")

# Un hecho que lcc sabe y el `.s` ya no dice, en un comentario (el ensamblador no lo ve):
#     ; @miniopt volatile NOMBRE
FACT_RE = re.compile(r"^\s*;\s*@miniopt\s+(volatile)\s+(\S+)\s*$")

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

    @property
    def opaque(self) -> bool:
        """Helper ensamblado del backend con convenio privado, no MiniABI C.

        Los `__mini_*` pueden devolver valores en R7-R10, enlazar por R15 o
        reservar R5-R9 como entradas. Optimizar su interior con el contrato C
        de `defs_uses()` no es seguro sin metadatos específicos.
        """
        if self.name.startswith("__mini_"):
            return True
        for line in self.body:
            if (line.kind == "instr" and line.op == "JR" and line.args
                    and line.args[0].strip().upper() != "R31"):
                return True
            if line.kind != "instr" or line.op != "JAL" or len(line.args) != 2:
                continue
            link, target = (arg.strip() for arg in line.args)
            if link.upper() != "R31" or target.startswith("__mini_"):
                return True
        return False


@dataclass
class Unit:
    path: str
    chunks: list = field(default_factory=list)   # Line o Function, en orden
    volatile: set[str] = field(default_factory=set)     # simbolos que lcc declaro `volatile` (`; @miniopt volatile`)

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
        fact = FACT_RE.match(raw)
        if fact:
            unit.volatile.add(fact.group(2))
            continue
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


def directive_parts(line: Line) -> list[str]:
    return line.text.replace(",", " ").split()
