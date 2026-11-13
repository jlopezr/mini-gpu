"""El `.s` troceado: lineas, funciones y unidades (`parse_unit` / `render_unit`)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LABEL_RE = re.compile(r"^([A-Za-z_.$@][A-Za-z0-9_.$@]*):\s*(.*)$")

# `runtime/gen_softfloat.py` renombra las `L.n` de los bloques embebidos a
# `__sf.n` para que no choquen con las del programa. Siguen siendo etiquetas de
# bloque, no comienzos de funcion: separarlas rompe el CFG y permite que DCE
# borre los valores que llegan a esos bloques. Las `__inl$...` del pase `marks`
# tampoco: marcan codigo expandido dentro de una funcion (al releer un `.opt.s`).
# build-c da a las `__sf.n` el sufijo de su unidad (`__sf.n.<unidad>`, ver `scope_statics`): siguen siendo
# de bloque.
# Las `__sfa.<...>` son las del runtime escrito a mano (u.lcc/runtime/softfloat_mini.s), tambien de bloque.
COMPILER_LOCAL_RE = re.compile(r"^L\.\d+$|^__sf\.\d+(?:\.\w+)?$|^__sfa\.[\w.]+$|^@|^__inl\$|^__ssy_")

SYMBOL_RE = re.compile(r"[A-Za-z_.$@][A-Za-z0-9_.$@]*")

# Un hecho que lcc sabe y el `.s` ya no dice, en un comentario (el ensamblador no lo ve):
#     ; @miniopt volatile NOMBRE      a NOMBRE no se le puede ahorrar ninguna lectura
#     ; @miniopt const NOMBRE         nadie escribe NOMBRE (escribir un objeto const es comportamiento indefinido)
#     ; @miniopt leafcall NOMBRE      un `JAL` a NOMBRE solo escribe R1-R6 (y el enlace): rutina de runtime escrita
#                                     a mano, sin pila (u.lcc/runtime/softfloat_mini.s); quien la llama deja vivos
#                                     sus temporales R7-R15 a traves de la llamada
FACT_RE = re.compile(r"^\s*;\s*@miniopt\s+(volatile|const|leafcall)\s+(\S+)\s*$")
# Dentro de una funcion, tras su etiqueta:
#     ; @miniopt ret32                la funcion devuelve 32 bits o nada: sus `JR R31` leen R1 y no R2 (sin el
#                                     hecho, un retorno puede ser de 64 bits en R1:R2)
RET32_RE = re.compile(r"^\s*;\s*@miniopt\s+ret32\s*$")
#     ; @miniopt clobber RN           RN deja de valer aqui (los argumentos de un intrinseco de `mini_ext.h`, que el
#                                     ABI de una llamada no conserva): se lee como una instruccion `CLOBBER RN` que
#                                     escribe RN y se vuelve a escribir como este comentario
CLOBBER_RE = re.compile(r"^\s*;\s*@miniopt\s+clobber\s+(R\d+)\s*$")

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
    # De que funciones expandidas viene (`inline`, `kernelcalls`), de fuera a dentro; `marks` lo pasa a etiquetas
    # para el perfil. () es de la propia funcion (lo pone `parse_line`); None, una linea que ha creado un pase:
    # `marks` le da el de sus vecinas.
    origin: tuple[str, ...] | None = field(default=None, compare=False)
    # Un `JR R31` de una funcion con `; @miniopt ret32`: el valor devuelto es solo R1 (ver `isa.defs_uses`).
    ret32: bool = field(default=False, compare=False)

    def render(self) -> str:
        if self.kind == "label":
            return f"{self.name}:"
        if self.kind == "instr":
            if self.op == "CLOBBER":
                return f"; @miniopt clobber {self.args[0]}"
            return f"{self.op} {', '.join(self.args)}" if self.args else self.op
        return self.text


def parse_line(raw: str) -> list[Line]:
    text = raw.split(";", 1)[0].strip() if '"' not in raw else raw.strip()
    if not text:
        return []
    out: list[Line] = []
    match = LABEL_RE.match(text)
    if match and not text.startswith("."):
        out.append(Line("label", "", name=match.group(1), origin=()))
        text = match.group(2).strip()
        if not text:
            return out
    if text.startswith("."):
        out.append(Line("directive", text, origin=()))
        return out
    op, _, rest = text.partition(" ")
    args = [a.strip() for a in rest.split(",")] if rest.strip() else []
    out.append(Line("instr", text, op=op.upper(), args=args, origin=()))
    return out


@dataclass
class Function:
    name: str
    header: list[Line]              # `.text`, `.globl f`, `.align 4` que la preceden
    body: list[Line]                # desde la etiqueta de la funcion inclusive
    ret32: bool = False             # `; @miniopt ret32`: devuelve 32 bits o nada

    @property
    def opaque(self) -> bool:
        """Helper ensamblado del backend con convenio privado, no MiniABI C.

        Los `__mini_*` pueden devolver valores en R7-R10, enlazar por R15 o
        reservar R5-R9 como entradas. Optimizar su interior con el contrato C
        de `defs_uses()` no es seguro sin metadatos específicos.
        """
        if self.name.startswith("__mini_"):
            return True
        # El runtime escrito a mano (u.lcc/runtime/softfloat_mini.s): lo declarado `leafcall` y sus bloques
        # privados `__sfa*`. Se encadenan con `BRA` y dejan valores en R5-R6 de un bloque a otro, y el modelo
        # de una funcion C no lo sabe. build-c llama `<nombre>.dup.<unidad>` a las copias repetidas.
        from .isa import LEAF_CALLS
        if self.name.startswith("__sfa") or self.name.split(".dup.", 1)[0] in LEAF_CALLS:
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
    const: set[str] = field(default_factory=set)        # objetos que lcc declaro `const` (`; @miniopt const`)

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
        if RET32_RE.match(raw):
            if current is not None:
                current.ret32 = True
            continue
        clobber = CLOBBER_RE.match(raw)
        if clobber and current is not None:
            release()
            current.body.append(Line("instr", raw.strip(), op="CLOBBER", args=[clobber.group(1)], origin=()))
            continue
        fact = FACT_RE.match(raw)
        if fact:
            if fact.group(1) == "leafcall":
                from .isa import declare_leaf_call
                declare_leaf_call(fact.group(2))
            else:
                (unit.volatile if fact.group(1) == "volatile" else unit.const).add(fact.group(2))
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
    for function in unit.functions():
        if function.ret32:
            for line in function.body:
                if line.kind == "instr" and line.op == "JR" and line.args and line.args[0].strip().upper() == "R31":
                    line.ret32 = True
    return unit


def render_unit(unit: Unit) -> str:
    return "\n".join(line.render() for line in unit.lines()) + "\n"


def directive_parts(line: Line) -> list[str]:
    return line.text.replace(",", " ").split()
