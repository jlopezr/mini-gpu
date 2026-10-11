#!/usr/bin/env python3
"""
MiniISA assembler.

Este modulo conserva el lenguaje del ensamblador actual: parser, directivas,
secciones, includes, simbolos, relajacion y pseudoinstrucciones. La codificacion
de instrucciones reales se delega en isa.py.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

import asm_output
import isa
from isa_core import ISAEncodingError

# ---------------------------------------------------------------------------
# ISA
# ---------------------------------------------------------------------------

INSTRUCTIONS = {instruction.name: instruction for instruction in isa.INSTRUCTIONS}


def operand_signature(name: str) -> tuple[str, ...]:
    return tuple(operand.name for operand in INSTRUCTIONS[name].operands)


def operand_kind(name: str, operand_name: str) -> str:
    for operand in INSTRUCTIONS[name].operands:
        if operand.name == operand_name:
            return operand.kind
    raise KeyError(operand_name)


REAL_OPS = set(INSTRUCTIONS)
def ops_with_signature(*signature: str) -> set[str]:
    return {
        name for name in REAL_OPS
        if operand_signature(name) == signature
    }


NO_OPERAND_OPS = ops_with_signature()
R3_OPS = ops_with_signature("Rd", "Ra", "Rb")
IMM5_OPS = ops_with_signature("Rd", "Ra", "imm5")
GETID_OPS = {
    name for name in REAL_OPS
    if operand_signature(name) == ("Rd",) and INSTRUCTIONS[name].fmt.name == "I"
}
I2_OPS = ops_with_signature("Rd", "imm16")
I3_OPS = ops_with_signature("Rd", "Ra", "imm16")
MEMORY_OPS = {
    name for name in I3_OPS
    if INSTRUCTIONS[name].category == "Memory"
}
BRANCH_OPS = ops_with_signature("Ra", "Rb", "target")
B_TARGET_OPS = ops_with_signature("target")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

REGISTER_RE = re.compile(r"^[Rr](\d+)$")
LABEL_RE = re.compile(r"^@?[A-Za-z_.$][A-Za-z0-9_.$]*$")
MEMORY_RE = re.compile(r"^(.+)\(([Rr]\d+)\)$")

# ---------------------------------------------------------------------------
# Etiquetas locales
#
# Una etiqueta que empieza por `@` pertenece a la ultima etiqueta global, y por
# dentro pasa a llamarse `global@local`. Como `@` solo se admite al PRINCIPIO
# de un nombre, ese nombre compuesto no lo puede escribir nadie a mano: no hay
# forma de chocar con el.
#
# Existen por los `.include`. Sin ellas, `drawline.inc` se apropiaba de nueve
# nombres globales --`dx_ready`, `skip_x`, `line_step`...-- de los que ocho son
# saltos internos que no le importan a nadie. Con `@`, reserva uno.
#
# El sigilo es `@` y no `.` porque un `.loop:` se lee como una directiva, ni `_`
# porque el backend de mini-lcc ya emite `_start` como simbolo global. `@` no
# lo usa nadie en el repo y es la convencion de MASM.
# ---------------------------------------------------------------------------

LOCAL_REF_RE = re.compile(r"@[A-Za-z0-9_.$]+")


def es_local(nombre: str) -> bool:
    return nombre.startswith("@")


def mangle_local(nombre: str, scope: str, donde: str) -> str:
    """`@loop` dentro de `drawline` -> `drawline@loop`."""
    if not scope:
        raise AsmError(
            f"{donde}: etiqueta local {nombre} sin ninguna etiqueta global "
            "antes a la que pertenecer"
        )
    return scope + nombre


def rewrite_locals(text: str, scope: str, donde: str) -> str:
    """Sustituye las referencias `@x` por su nombre compuesto.

    Se hace en la pasada 1, igual que los `.include`: a partir de ahi el resto
    del ensamblador no sabe que existen las etiquetas locales, y `resolve_target`
    y compañia siguen viendo nombres normales.
    """
    return LOCAL_REF_RE.sub(lambda m: mangle_local(m.group(0), scope, donde), text)


# Nombre del origen cuando el fuente llega como cadena y no como fichero: los
# simuladores ensamblan programas incrustados en sus tests, y ahi no hay ruta
# que citar. Con este centinela los mensajes siguen diciendo "linea N" como
# siempre; en cuanto hay fichero, pasan a decir "fichero:N".
ENTRADA = "<entrada>"

# Tope de anidamiento de `.include`. La deteccion de ciclos ya corta el caso
# patologico; esto ataja la cadena larga pero finita, que produciria un
# RecursionError de Python en vez de un error de ensamblado legible.
INCLUDE_MAX_DEPTH = 16


class AsmError(ValueError):
    """Error de ensamblado, con linea y motivo.

    Hereda de ValueError, y no de Exception, para que los simuladores lo
    presenten como lo que es: una entrada mala, no un fallo del simulador. Los
    tres ya envuelven la carga en `except ValueError` y la imprimen con su
    prefijo; sin esto, un .asm con una errata salia como traceback pelado desde
    que los lanzadores ensamblan. Quien capturaba AsmError lo sigue capturando.
    """


@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    column: int = 1


@dataclass
class SourceLine:
    number: int
    text: str
    pc: int
    section: str = ".text"
    origin: str = ENTRADA
    # Bytes que ocupa la línea ya colocada. Lo fija la pasada 1: un `LI` con
    # etiqueta mide 4 u 8 según adónde caiga, y el texto solo ya no lo dice.
    size: int = 4

    @property
    def location(self) -> SourceLocation:
        return SourceLocation(self.origin, self.number)


@dataclass
class Section:
    name: str
    data: bytearray = field(default_factory=bytearray)
    alignment: int = 4
    bss_size: int = 0


@dataclass
class Symbol:
    name: str
    section: str | None
    offset: int
    binding: str = "local"
    source: SourceLocation | None = None
    kind: str = "label"
    defined: bool = True


@dataclass(frozen=True)
class Expression:
    symbol: str | None
    addend: int = 0


@dataclass
class Relocation:
    section: str
    offset: int
    symbol: str
    kind: str
    addend: int = 0
    source: SourceLocation | None = None
    resolved: bool = False
    bit_offset: int = 0
    bit_size: int = 32
    mask: int = 0xFFFFFFFF


@dataclass
class Fragment:
    section: str
    offset: int
    size: int
    source: SourceLocation
    text: str
    kind: str = "unknown"
    data: bytes = b""


@dataclass
class AssemblyResult:
    sections: dict[str, Section]
    symbols: dict[str, Symbol]
    relocations: list[Relocation]
    fragments: list[Fragment]
    image: bytes
    address_to_source: dict[int, SourceLocation]


def strip_comment(line: str) -> str:
    """Quita el comentario, respetando lo que haya entre comillas.

    Las comillas importan desde que existe `.string`: un `;` o un `#` dentro
    de un mensaje son parte del mensaje, no el principio de un comentario.
    """
    dentro = False
    escapado = False
    for index, char in enumerate(line):
        if escapado:
            escapado = False
            continue
        if char == "\\" and dentro:
            escapado = True
            continue
        if char == '"':
            dentro = not dentro
            continue
        if not dentro and char in (";", "#"):
            return line[:index].strip()
    return line.strip()


# ---------------------------------------------------------------------------
# Directivas y secciones
#
# El ensamblador solo sabia emitir instrucciones, asi que un programa que
# necesitara una tabla o un mensaje tenia que construirlo en tiempo de
# ejecucion a base de MOVI y STORE. Con `.word` y `.string` los datos van en la
# imagen, que es donde deben estar.
#
# La salida sigue siendo una imagen plana. Las secciones solo sirven para
# aceptar salida de compiladores y reordenarla internamente:
#
#   .text -> .rodata -> .data -> .bss
#
# No hay formato objeto, relocations ni linker: los simbolos se resuelven a
# direcciones absolutas dentro de esa imagen plana.
# ---------------------------------------------------------------------------

ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", '"': '"'}
SECTION_ORDER = [".text", ".rodata", ".data", ".bss"]
SECTION_ALIASES = {
    ".text": ".text",
    ".code": ".text",
    ".rodata": ".rodata",
    ".rdata": ".rodata",
    ".data": ".data",
    ".bss": ".bss",
}
SECTION_DIRECTIVES = set(SECTION_ALIASES)
IGNORED_DIRECTIVES = {
    ".GLOBL", ".GLOBAL", ".EXTERN", ".ENT", ".END",
    ".TYPE", ".SIZE", ".FILE", ".LOC", ".IDENT",
}


def parse_string_literal(text: str) -> bytes:
    text = text.strip()
    if len(text) < 2 or not text.startswith('"') or not text.endswith('"'):
        raise AsmError('.string requiere un literal entre comillas dobles')

    out = bytearray()
    index = 1
    end = len(text) - 1
    while index < end:
        char = text[index]
        if char == "\\":
            index += 1
            if index >= end:
                raise AsmError("escape incompleto al final de la cadena")
            if text[index] not in ESCAPES:
                raise AsmError(f"escape desconocido: \\{text[index]}")
            out += ESCAPES[text[index]].encode("latin-1")
        else:
            out += char.encode("latin-1")
        index += 1
    # NUL final: las rutinas de impresion recorren hasta el cero.
    out += b"\x00"
    while len(out) % 4:
        out += b"\x00"
    return bytes(out)


def align_to(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    return (value + alignment - 1) & ~(alignment - 1)


def parse_alignment(operand_text: str) -> int:
    ops = split_operands(operand_text)
    if len(ops) != 1:
        raise AsmError(".align requiere exactamente un operando")
    alignment = parse_int(ops[0])
    if alignment < 0:
        raise AsmError(".align no puede ser negativo")
    return 1 if alignment == 0 else alignment


def normalize_section(name: str) -> str:
    key = name.strip().split(",", 1)[0].lower()
    if key not in SECTION_ALIASES:
        raise AsmError(f"seccion desconocida: {name}")
    return SECTION_ALIASES[key]


def read_hex_image(path: Path) -> bytes:
    """Lee el formato .hex del ensamblador: una palabra de 32 bits por linea."""
    out = bytearray()
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        raise AsmError(f"no se puede leer {path}: {error}") from None
    for number, raw in enumerate(lines, 1):
        token = raw.strip()
        if not token:
            continue
        try:
            value = int(token, 16)
        except ValueError:
            raise AsmError(
                f"{path}:{number}: palabra hexadecimal invalida: {token}"
            ) from None
        if not 0 <= value <= 0xFFFFFFFF:
            raise AsmError(
                f"{path}:{number}: palabra hexadecimal fuera de 32 bits: {token}"
            )
        out += value.to_bytes(4, "little")
    return bytes(out)


def read_incbin(path: Path) -> bytes:
    suffix = path.suffix.lower()
    if suffix == ".hex":
        return read_hex_image(path)
    if suffix == ".bin":
        try:
            return path.read_bytes()
        except OSError as error:
            raise AsmError(f"no se puede leer {path}: {error}") from None
    raise AsmError(f".incbin solo admite ficheros .bin o .hex: {path.name}")


def directive_size_bytes(mnemonic: str, operand_text: str, pc: int) -> int:
    """Cuantos bytes ocupa, sin resolver etiquetas.

    Hace falta en la pasada 1, donde todavia no se sabe donde esta cada
    etiqueta pero si CUANTOS bytes emite la directiva. Sin esto, toda
    etiqueta posterior a una tabla apuntaria mal.
    """
    if mnemonic == ".WORD":
        valores = split_operands(operand_text)
        if not valores:
            raise AsmError(".word requiere al menos un valor")
        return 4 * len(valores)
    if mnemonic == ".HALF":
        valores = split_operands(operand_text)
        if not valores:
            raise AsmError(".half requiere al menos un valor")
        return 2 * len(valores)
    if mnemonic == ".BYTE":
        valores = split_operands(operand_text)
        if not valores:
            raise AsmError(".byte requiere al menos un valor")
        return len(valores)
    if mnemonic == ".STRING":
        return len(parse_string_literal(operand_text))
    if mnemonic == ".INCBIN":
        return len(read_incbin(Path(parse_include_path(operand_text))))
    if mnemonic in {".SPACE", ".ZERO"}:
        valores = split_operands(operand_text)
        if len(valores) != 1:
            raise AsmError(f"{mnemonic.lower()} requiere exactamente un valor")
        size = parse_int(valores[0])
        if size < 0:
            raise AsmError(f"{mnemonic.lower()} no puede ser negativo")
        return size
    if mnemonic == ".ALIGN":
        return align_to(pc, parse_alignment(operand_text)) - pc
    if mnemonic in IGNORED_DIRECTIVES:
        return 0
    raise AsmError(f"directiva desconocida: {mnemonic}")


def li_short_literal(operand_text: str) -> int | None:
    """El valor de `LI Rd, literal` si cabe en un `MOVI` (signed16), o None.

    Solo un literal numerico se decide aqui, con el texto. Los que llevan una
    etiqueta o un `.equ` no tienen valor hasta colocar la imagen: se relajan en
    `layout_pass` (ver `li_has_label`). Un literal numerico fuera de rango sigue
    midiendo dos palabras aunque quepa en 16 bits sin signo; solo se relajan
    los simbolicos. `LA` se queda siempre en dos (es el "dame la direccion
    completa").
    """
    ops = split_operands(operand_text)
    if len(ops) != 2:
        return None
    try:
        value = parse_int(ops[1])
    except AsmError:
        return None
    return value if -(1 << 15) <= value < (1 << 15) else None


# Rango de un `LI` simbolico de una palabra: `MOVI` llega a 32767 (extiende el
# signo) y `ORI Rd, R0, v` hasta 65535 (rellena con ceros).
LI_SHORT_MIN = -(1 << 15)
LI_SHORT_MAX = (1 << 16) - 1


def li_has_label(text: str) -> bool:
    """¿Es un `LI Rd, expr` cuyo operando no es un literal numerico?

    Esos son los candidatos a relajarse a una palabra."""
    parts = text.split(None, 1)
    if parts[0].upper() != "LI" or len(parts) < 2:
        return False
    ops = split_operands(parts[1])
    if len(ops) != 2:
        return False
    try:
        parse_int(ops[1])
    except AsmError:
        return True
    return False


def instruction_size_bytes(text: str) -> int:
    parts = text.split(None, 1)
    mnemonic = parts[0].upper()
    if mnemonic == "LI":
        operand_text = parts[1] if len(parts) > 1 else ""
        return 4 if li_short_literal(operand_text) is not None else 8
    if mnemonic == "LA":
        return 8
    return 4


def directive_bytes(mnemonic: str, operand_text: str,
                    labels: dict[str, int]) -> bytes:
    """Convierte una directiva en los bytes que emite.

    `.word` acepta etiquetas, que es lo que permite escribir una tabla de
    direcciones --un diccionario de Forth, por ejemplo-- sin calcularlas a
    mano.
    """
    if mnemonic == ".WORD":
        out = bytearray()
        for token in split_operands(operand_text):
            value = resolve_target(token, labels)
            if not -(1 << 31) <= value <= (1 << 32) - 1:
                raise AsmError(f".word fuera de rango de 32 bits: {value}")
            out += int(value & 0xFFFFFFFF).to_bytes(4, "little")
        return bytes(out)
    if mnemonic == ".HALF":
        out = bytearray()
        for token in split_operands(operand_text):
            value = resolve_target(token, labels)
            if not -(1 << 15) <= value <= (1 << 16) - 1:
                raise AsmError(f".half fuera de rango de 16 bits: {value}")
            out += int(value & 0xFFFF).to_bytes(2, "little")
        return bytes(out)
    if mnemonic == ".BYTE":
        out = bytearray()
        for token in split_operands(operand_text):
            value = resolve_target(token, labels)
            if not -(1 << 7) <= value <= (1 << 8) - 1:
                raise AsmError(f".byte fuera de rango de 8 bits: {value}")
            out += int(value & 0xFF).to_bytes(1, "little")
        return bytes(out)
    if mnemonic == ".STRING":
        return parse_string_literal(operand_text)
    if mnemonic == ".INCBIN":
        return read_incbin(Path(parse_include_path(operand_text)))
    if mnemonic in {".SPACE", ".ZERO"}:
        return b"\x00" * directive_size_bytes(mnemonic, operand_text, 0)
    if mnemonic == ".ALIGN" or mnemonic in IGNORED_DIRECTIVES:
        return b""
    raise AsmError(f"directiva desconocida: {mnemonic}")


def is_directive(text: str) -> bool:
    return text.split(None, 1)[0].startswith(".")


def ubicacion(origin: str, number: int) -> str:
    """Como se cita una linea en un mensaje de error.

    Sin fichero se sigue diciendo "linea N", que es lo que decia el
    ensamblador antes de que existieran los `.include` y lo que esperan los
    tests que ensamblan cadenas.
    """
    return f"línea {number}" if origin == ENTRADA else f"{origin}:{number}"


def parse_include_path(operand_text: str) -> str:
    """La ruta de un `.include`, entre comillas dobles.

    No reutiliza `parse_string_literal` porque aquella sirve a `.string`: le
    añade un NUL final y rellena hasta multiplo de 4, que en una ruta serian
    basura. Tampoco interpreta escapes: una ruta se escribe con barras hacia
    delante y asi vale igual en Windows que en Linux.
    """
    text = operand_text.strip()
    if len(text) < 2 or not text.startswith('"') or not text.endswith('"'):
        raise AsmError('.include requiere una ruta entre comillas dobles')
    ruta = text[1:-1]
    if not ruta:
        raise AsmError(".include con ruta vacia")
    return ruta


def buscar_include(ruta: str, base_dir: Path | None,
                   include_dirs: tuple[Path, ...]) -> Path | None:
    """Resuelve la ruta de un `.include`, o None si no aparece en ningun sitio.

    Orden: primero la carpeta del fichero que incluye, y despues las carpetas
    de `-I` en el orden en que se dieron. La carpeta del fuente va primero a
    proposito: un `.include "trozo.inc"` al lado del programa tiene que ganar
    a uno del mismo nombre en la biblioteca compartida, o cambiar la
    biblioteca romperia programas ajenos en silencio.
    """
    destino = Path(ruta)
    if destino.is_absolute():
        return destino if destino.is_file() else None

    candidatas = []
    if base_dir is not None:
        candidatas.append(base_dir / destino)
    candidatas.extend(carpeta / destino for carpeta in include_dirs)

    for candidata in candidatas:
        if candidata.is_file():
            return candidata
    return None


# Etiquetas internas del compilador: lcc numera `L.1`, `L.2`... desde 1 en CADA
# compilacion, asi que dos `.s` de lcc incluidos desde un mismo fuente chocarian
# en `L.2`. Son privadas del fichero donde aparecen, no de la funcion: lcc las usa
# tambien para datos (literales de cadena, constantes) que varias funciones
# referencian. El fuente principal conserva sus nombres; cada fichero incluido
# pasa a `L.<n>.<k>`, con `n` su orden de inclusion (1, 2...).
COMPILER_LABEL_RE = re.compile(r"\bL\.(\d+)\b")


def scope_compiler_labels(raw: str, tag: int) -> str:
    """`L.k` -> `L.<tag>.k` fuera de las cadenas. `tag == 0` (fuente principal) no cambia."""
    if tag == 0 or "L." not in raw:
        return raw
    pieces: list[str] = []
    start = 0
    inside = False
    escaped = False
    for index, char in enumerate(raw):
        if escaped:
            escaped = False
        elif char == "\\" and inside:
            escaped = True
        elif char == '"':
            piece = raw[start:index]
            pieces.append(piece if inside else
                          COMPILER_LABEL_RE.sub(lambda m: f"L.{tag}.{m.group(1)}", piece))
            start = index
            inside = not inside
    tail = raw[start:]
    pieces.append(tail if inside else
                  COMPILER_LABEL_RE.sub(lambda m: f"L.{tag}.{m.group(1)}", tail))
    return "".join(pieces)


CONDITIONAL_DIRECTIVES = {".IFDEF", ".IFNDEF", ".ELSE", ".ENDIF"}
DEFINE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


def parse_define_name(name: str) -> str:
    """Un nombre valido para `-D` y para `.ifdef`/`.ifndef`."""
    if not DEFINE_NAME_RE.fullmatch(name):
        raise AsmError(f"nombre de simbolo invalido: {name!r}")
    return name


def expand_includes(source: str, base_dir: Path | None = None,
                    origin: str = ENTRADA,
                    include_dirs: tuple[Path, ...] = (),
                    defines: frozenset[str] = frozenset(),
                    _stack: tuple[Path, ...] = (),
                    _once: set[Path] | None = None,
                    _counter: list[int] | None = None,
                    _tag: int = 0) -> list[tuple[str, int, str]]:
    """Resuelve los `.include` y devuelve (origen, numero, linea) en orden.

    Se hace ANTES de la pasada 1, de modo que el resto del ensamblador sigue
    viendo una secuencia plana de lineas y no se entera de que hubo ficheros.
    Lo unico que cambia es que cada linea recuerda de donde vino, que es lo
    que permite que un label duplicado diga los DOS sitios.

    Las rutas son relativas al fichero que incluye, no al directorio actual.
    Si fueran relativas al directorio actual, `cube.asm` solo ensamblaria
    ejecutando desde su propia carpeta, y los lanzadores del repo llaman al
    ensamblador desde la raiz.
    """
    filas: list[tuple[str, int, str]] = []
    # Conjunto compartido por TODA la expansion, no por nivel: un fichero con
    # `.once` incluido desde dos ramas distintas del arbol tiene que entrar una
    # sola vez, no una por rama.
    if _once is None:
        _once = set()
    if _counter is None:
        _counter = [0]
        # Un conjunto por expansion, no por fichero: un `.define` en un .asm
        # tiene que verlo el .inc que se incluya despues, y `-D` no se muta.
        defines = set(defines)

    # Un `.ifdef` abierto por nivel: [rama del padre activa, condicion cumplida,
    # ya en el `.else`, linea del `.ifdef`]. Vive en esta llamada, no en la
    # expansion entera, porque cada `.ifdef` se cierra en el fichero que lo abre.
    condiciones: list[list] = []
    activa = True

    for number, raw in enumerate(source.splitlines(), 1):
        text = strip_comment(raw)
        partes = text.split(None, 1) if text and is_directive(text) else []
        mnemonic = partes[0].upper() if partes else ""

        if mnemonic in CONDITIONAL_DIRECTIVES:
            try:
                if mnemonic in {".IFDEF", ".IFNDEF"}:
                    nombre = parse_define_name(partes[1].strip() if len(partes) > 1 else "")
                    cumple = (nombre in defines) == (mnemonic == ".IFDEF")
                    condiciones.append([activa, cumple, False, number])
                    activa = activa and cumple
                    continue
                if not condiciones:
                    raise AsmError(f"{mnemonic.lower()} sin .ifdef/.ifndef")
                if len(partes) > 1:
                    raise AsmError(f"{mnemonic.lower()} no admite operandos")
                if mnemonic == ".ELSE":
                    if condiciones[-1][2]:
                        raise AsmError(".else repetido")
                    condiciones[-1][2] = True
                    activa = condiciones[-1][0] and not condiciones[-1][1]
                else:
                    activa = condiciones.pop()[0]
            except AsmError as error:
                raise AsmError(f"{ubicacion(origin, number)}: {error}") from None
            continue

        if not activa:
            continue

        if not text or not is_directive(text):
            filas.append((origin, number, scope_compiler_labels(raw, _tag)))
            continue

        if mnemonic == ".DEFINE":
            try:
                if len(partes) < 2:
                    raise AsmError(".define requiere un nombre")
                defines.add(parse_define_name(partes[1].strip()))
            except AsmError as error:
                raise AsmError(f"{ubicacion(origin, number)}: {error}") from None
            continue

        if mnemonic == ".ONCE":
            # El fichero se declara idempotente. Se aprende al incluirlo la
            # primera vez --hay que leerlo para verlo-- y a partir de ahi las
            # siguientes inclusiones se saltan enteras.
            #
            # En el fichero principal no hace nada, y eso es deliberado en vez
            # de un error: un .asm puede querer ensamblarse suelto Y ser
            # incluido por otro, y marcarlo no deberia impedir lo primero.
            if _stack:
                _once.add(_stack[-1])
            continue

        if mnemonic not in {".INCLUDE", ".INCBIN"}:
            filas.append((origin, number, scope_compiler_labels(raw, _tag)))
            continue

        try:
            ruta = parse_include_path(partes[1] if len(partes) > 1 else "")
        except AsmError as error:
            raise AsmError(f"{ubicacion(origin, number)}: {error}") from None

        if base_dir is None and not include_dirs and not Path(ruta).is_absolute():
            raise AsmError(
                f"{ubicacion(origin, number)}: {mnemonic.lower()} con ruta relativa "
                f"({ruta}) pero el fuente no viene de un fichero ni se dio "
                "ninguna carpeta de busqueda (-I), asi que no hay desde donde "
                "resolverla"
            )

        destino = buscar_include(ruta, base_dir, include_dirs)
        if destino is None:
            miradas = []
            if base_dir is not None:
                miradas.append(str(base_dir))
            miradas.extend(str(c) for c in include_dirs)
            raise AsmError(
                f"{ubicacion(origin, number)}: no encuentro {ruta}; "
                f"mirado en: {', '.join(miradas)}"
            )

        try:
            resuelto = destino.resolve()
        except OSError as error:
            raise AsmError(f"{ubicacion(origin, number)}: {ruta}: {error}") from None

        if mnemonic == ".INCBIN":
            # Las dos pasadas deben abrir el mismo fichero. La ruta absoluta
            # conserva ademas la carpeta de un .include anidado.
            filas.append((origin, number, f'.incbin "{resuelto.as_posix()}"'))
            continue

        if resuelto in _once:
            # Ya entro y se habia declarado `.once`. Saltarlo no es un caso
            # raro: es lo que permite que drawline.inc pida putpixel.inc por su
            # cuenta sin chocar con el programa que tambien lo incluye.
            continue

        if resuelto in _stack:
            cadena = " -> ".join(p.name for p in _stack) + f" -> {resuelto.name}"
            raise AsmError(
                f"{ubicacion(origin, number)}: .include circular: {cadena}"
            )
        if len(_stack) >= INCLUDE_MAX_DEPTH:
            raise AsmError(
                f"{ubicacion(origin, number)}: .include anidado mas de "
                f"{INCLUDE_MAX_DEPTH} niveles"
            )

        try:
            incluido = resuelto.read_text(encoding="utf-8")
        except OSError as error:
            raise AsmError(f"{ubicacion(origin, number)}: {error}") from None

        # El fichero incluido resuelve SUS `.include` desde su propia carpeta,
        # no desde la del programa que lo incluyo. Asi un .inc que se apoya en
        # otro sigue funcionando desde donde sea que lo incluyan.
        _counter[0] += 1
        filas.extend(expand_includes(
            incluido, resuelto.parent, resuelto.name,
            include_dirs, defines, _stack + (resuelto,), _once, _counter,
            _counter[0]
        ))

    if condiciones:
        raise AsmError(
            f"{ubicacion(origin, condiciones[-1][3])}: .ifdef sin .endif")

    return filas


def split_operands(s: str) -> list[str]:
    if not s.strip():
        return []
    return [x.strip() for x in s.split(",")]


def parse_reg(token: str) -> int:
    m = REGISTER_RE.match(token)
    if not m:
        raise AsmError(f"registro inválido: {token}")
    value = int(m.group(1))
    if not 0 <= value <= 31:
        raise AsmError(f"registro fuera de rango: {token}")
    return value


def parse_int(token: str) -> int:
    token = token.strip()
    if "+" in token[1:] or "-" in token[1:]:
        parts = re.findall(r"[+-]?[^+-]+", token)
        if len(parts) > 1 and "".join(parts) == token:
            return sum(parse_int(part) for part in parts)
    try:
        return int(token, 0)
    except ValueError:
        raise AsmError(f"entero inválido: {token}") from None


def check_signed(value: int, bits: int, what: str) -> int:
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    if not lo <= value <= hi:
        raise AsmError(f"{what} fuera de rango signed{bits}: {value}")
    return value & ((1 << bits) - 1)


def check_unsigned(value: int, bits: int, what: str) -> int:
    hi = (1 << bits) - 1
    if not 0 <= value <= hi:
        raise AsmError(f"{what} fuera de rango unsigned{bits}: {value}")
    return value


def require_signed(value: int, bits: int, what: str) -> int:
    check_signed(value, bits, what)
    return value


def require_unsigned(value: int, bits: int, what: str) -> int:
    check_unsigned(value, bits, what)
    return value


def encode_real(name: str, **operands: int) -> int:
    try:
        return isa.encode(name, **operands)
    except ISAEncodingError as error:
        raise AsmError(str(error)) from None


def target_width(name: str) -> int:
    for operand in INSTRUCTIONS[name].operands:
        if operand.name == "target":
            return operand.width
    raise AsmError(f"{name}: no tiene operando target")


def require_operands(mnemonic: str, ops: list[str], count: int,
                     syntax: str) -> None:
    if len(ops) != count:
        raise AsmError(f"{mnemonic} requiere: {syntax}")


def imm16_for(mnemonic: str, text: str, labels: dict[str, int]) -> int:
    if operand_kind(mnemonic, "imm16") in {"simm", "branch"}:
        return require_signed(resolve_target(text, labels), 16,
                              f"inmediato {mnemonic}")

    # MOVHI conservaba una restriccion historica: solo literal numerico.
    value = parse_int(text) if mnemonic == "MOVHI" else resolve_target(text, labels)
    return require_unsigned(value, 16, f"inmediato {mnemonic}")


def branch_word_offset(mnemonic: str, target: str, line: SourceLine,
                       labels: dict[str, int]) -> int:
    target_pc = resolve_target(target, labels)
    return branch_offset(target_pc, line.pc, target_width(mnemonic))


def parse_i3_operands(mnemonic: str, ops: list[str]) -> tuple[int, int, str]:
    if len(ops) == 2 and mnemonic in MEMORY_OPS:
        match = MEMORY_RE.match(ops[1])
        if not match:
            raise AsmError(f"{mnemonic} requiere: X, Y, imm16")
        return parse_reg(ops[0]), parse_reg(match.group(2)), match.group(1)

    require_operands(mnemonic, ops, 3, "X, Y, imm16")
    return parse_reg(ops[0]), parse_reg(ops[1]), ops[2]


# ---------------------------------------------------------------------------
# Pass 1
# ---------------------------------------------------------------------------

@dataclass
class Layout:
    """Lo que la pasada 1 sabe de la imagen y `first_pass` no devuelve.

    Lo usa el listado para decir en qué sección está cada etiqueta y cuánto
    ocupa cada sección; `first_pass` lo descarta para no cambiar su firma.
    """
    label_section: dict[str, str]      # etiqueta -> sección en que cae
    comm_sizes: dict[str, int]         # símbolos `.comm` -> su tamaño exacto
    section_base: dict[str, int]       # sección -> dirección inicial
    section_size: dict[str, int]       # sección -> bytes que ocupa
    symbol_sources: dict[str, SourceLocation]
    externs: set[str]                  # símbolos importados de otro objeto
    globals: set[str]                  # símbolos exportados para el linker


def first_pass(source: str,
               base_dir: Path | None = None,
               origin: str = ENTRADA,
               include_dirs: tuple[Path, ...] = (),
               defines: frozenset[str] = frozenset(),
               ) -> tuple[list[SourceLine], dict[str, int], int, dict[str, int]]:
    lines, labels, image_size, equates, _ = layout_pass(
        source, base_dir, origin, include_dirs, defines)
    return lines, labels, image_size, equates


def layout_pass(source: str,
                base_dir: Path | None = None,
                origin: str = ENTRADA,
                include_dirs: tuple[Path, ...] = (),
                defines: frozenset[str] = frozenset(),
                ) -> tuple[list[SourceLine], dict[str, int], int,
                           dict[str, int], Layout]:
    """Pasada 1 con relajación de `LI Rd, etiqueta`.

    El tamaño de ese `LI` depende de la dirección de la etiqueta, y la
    dirección depende de los tamaños. Se resuelve por punto fijo: se parte de
    que todos caben en una palabra, se coloca todo, y los que no caben en 16
    bits se alargan a dos; se repite hasta que no cambie ninguno.

    Termina, y en el mínimo, porque alargar un `LI` solo empuja las
    direcciones hacia arriba (el relleno de `.align` también es monótono en la
    posición): uno que no cabe ya no puede volver a caber.
    """
    shrunk: set[int] | None = None      # None: todos los candidatos, primera vez
    while True:
        lines, labels, image_size, equates, info, candidates = _layout_once(
            source, base_dir, origin, include_dirs, defines, shrunk)
        actual = set(range(len(candidates))) if shrunk is None else shrunk
        keep = {i for i in actual if li_label_fits(candidates[i], labels,
                                                   info.externs)}
        if keep == actual:
            return lines, labels, image_size, equates, info
        shrunk = keep


def li_label_fits(operand: str, labels: dict[str, int],
                  externs: set[str] | None = None) -> bool:
    """¿Cabe el valor de `LI Rd, operand` en una sola palabra?

    Rango de `LI_SHORT_MIN`..`LI_SHORT_MAX`: de -32768 a 32767 sale un `MOVI`
    (extiende el signo) y de 32768 a 65535 un `ORI Rd, R0, v` (rellena con
    ceros). Un nombre sin resolver no cabe: se queda en dos palabras y el
    error de «etiqueta no definida» salta en la pasada 2, como antes.
    """
    if externs and any(part.strip("+- ") in externs
                       for part in re.findall(r"[+-]?[^+-]+", operand)):
        return False
    try:
        value = resolve_target(operand, labels)
    except AsmError:
        return False
    return LI_SHORT_MIN <= value <= LI_SHORT_MAX


def _layout_once(source: str,
                 base_dir: Path | None,
                 origin: str,
                 include_dirs: tuple[Path, ...],
                 defines: frozenset[str],
                 shrunk: set[int] | None,
                 ) -> tuple[list[SourceLine], dict[str, int], int,
                            dict[str, int], Layout, list[str]]:
    """Una colocación completa. `shrunk` son los `LI` con etiqueta (numerados
    por orden de aparición) que miden 4 bytes; `None` es «todos». Devuelve
    además el operando de cada uno, para que `layout_pass` compruebe si cabe."""
    candidates: list[str] = []
    comm_sizes: dict[str, int] = {}
    label_offsets: dict[str, tuple[str, int]] = {}
    label_origins: dict[str, str] = {}
    symbol_sources: dict[str, SourceLocation] = {}
    externs: set[str] = set()
    globals_: set[str] = set()
    # Constantes de `.equ`. Van aparte de `label_offsets` porque no pertenecen a
    # ninguna seccion: su valor es absoluto y no se desplaza al colocar la
    # imagen. Se funden con las etiquetas al final, en un unico espacio de
    # nombres, para que `resolve_target` no tenga que saber de cual viene cada
    # nombre.
    equates: dict[str, int] = {}
    lines: list[SourceLine] = []
    offsets = {name: 0 for name in SECTION_ORDER}
    section = ".text"
    scope = ""          # ultima etiqueta global; a ella pertenecen las `@`

    for origin, number, raw in expand_includes(source, base_dir, origin, include_dirs, defines):
        text = strip_comment(raw)
        if not text:
            continue

        # Permitimos:
        #   label:
        #   label: ADD R1,R2,R3
        while ":" in text:
            lhs, rhs = text.split(":", 1)
            label = lhs.strip()

            if not LABEL_RE.match(label):
                break

            if es_local(label):
                label = mangle_local(label, scope, ubicacion(origin, number))
            else:
                # Abre ambito: las `@` que vengan detras le pertenecen.
                scope = label

            if label in equates:
                raise AsmError(
                    f"{ubicacion(origin, number)}: {label} ya es una constante "
                    f".equ (definida en {label_origins[label]})"
                )

            if label in externs:
                raise AsmError(
                    f"{ubicacion(origin, number)}: label duplicado: {label} "
                    f"(declarado .extern en {label_origins[label]})"
                )

            if label in label_offsets:
                # Con `.include`, el duplicado suele estar en OTRO fichero, y
                # decir solo "label duplicado" obliga a buscarlo a mano. Es el
                # riesgo principal de incluir ensamblador: no hay espacios de
                # nombres, asi que el mensaje tiene que hacer de indice.
                raise AsmError(
                    f"{ubicacion(origin, number)}: label duplicado: {label} "
                    f"(ya definido en {label_origins[label]})"
                )

            label_offsets[label] = (section, offsets[section])
            label_origins[label] = ubicacion(origin, number)
            symbol_sources[label] = SourceLocation(origin, number)
            text = rhs.strip()

            if not text:
                break

        if not text:
            continue

        partes = text.split(None, 1)
        mnemonic = partes[0].upper()
        operand_text = partes[1] if len(partes) > 1 else ""

        # Referencias a etiquetas locales. Se saltan las cadenas, donde una
        # `@` es parte del mensaje y no un nombre.
        if mnemonic != ".STRING" and "@" in text:
            text = rewrite_locals(text, scope, ubicacion(origin, number))
            partes = text.split(None, 1)
            operand_text = partes[1] if len(partes) > 1 else ""

        if is_directive(text):
            try:
                if mnemonic in {".SECTION", ".SEGMENT"}:
                    if not operand_text:
                        raise AsmError(f"{mnemonic.lower()} requiere nombre")
                    section = normalize_section(operand_text)
                    continue
                if mnemonic.lower() in SECTION_DIRECTIVES:
                    section = normalize_section(mnemonic)
                    continue
                if mnemonic in {".EQU", ".SET"}:
                    ops = split_operands(operand_text)
                    if len(ops) != 2:
                        raise AsmError(
                            f"{mnemonic.lower()} requiere: nombre, valor")
                    name = ops[0]
                    if not LABEL_RE.match(name) or es_local(name):
                        raise AsmError(f"nombre de {mnemonic.lower()} invalido: {name}")
                    if name in equates:
                        raise AsmError(
                            f"constante duplicada: {name} "
                            f"(ya definida en {label_origins[name]})"
                        )
                    if name in label_offsets:
                        raise AsmError(
                            f"{name} ya es una etiqueta "
                            f"(definida en {label_origins[name]})"
                        )
                    if name in externs:
                        raise AsmError(
                            f"{name} ya es un simbolo .extern "
                            f"(declarado en {label_origins[name]})"
                        )
                    # El valor se resuelve AQUI, contra las constantes ya
                    # definidas y nada mas. Una `.equ` no puede referirse a una
                    # etiqueta ni a una constante posterior: en la pasada 1 las
                    # etiquetas todavia no tienen direccion, y admitir
                    # referencias hacia delante obligaria a un solucionador de
                    # dependencias. El contrato de mmio.md §20 pide justo lo
                    # contrario --una fuente tonta-- asi que la limitacion es
                    # deliberada y el error lo dice.
                    try:
                        value = resolve_target(ops[1], equates)
                    except AsmError:
                        raise AsmError(
                            f"valor de {mnemonic.lower()} no resoluble: {ops[1]} "
                            f"(solo admite enteros y constantes .equ ya definidas)"
                        ) from None
                    equates[name] = value
                    label_origins[name] = ubicacion(origin, number)
                    symbol_sources[name] = SourceLocation(origin, number)
                    continue

                if mnemonic == ".EXTERN":
                    ops = split_operands(operand_text)
                    if not ops:
                        raise AsmError(".extern requiere al menos un simbolo")
                    for name in ops:
                        if not LABEL_RE.match(name) or es_local(name):
                            raise AsmError(f"simbolo .extern invalido: {name}")
                        if name in label_offsets or name in equates:
                            raise AsmError(
                                f"{name} ya esta definido "
                                f"(definido en {label_origins[name]})"
                            )
                        if name in externs:
                            continue
                        externs.add(name)
                        label_origins[name] = ubicacion(origin, number)
                        symbol_sources[name] = SourceLocation(origin, number)
                    continue

                if mnemonic in {".GLOBAL", ".GLOBL"}:
                    ops = split_operands(operand_text)
                    if not ops:
                        raise AsmError(f"{mnemonic.lower()} requiere al menos un simbolo")
                    for name in ops:
                        if not LABEL_RE.match(name) or es_local(name):
                            raise AsmError(f"simbolo {mnemonic.lower()} invalido: {name}")
                        if name in externs:
                            raise AsmError(
                                f"{name} ya es un simbolo .extern "
                                f"(declarado en {label_origins[name]})"
                            )
                        globals_.add(name)
                    continue

                if mnemonic == ".COMM":
                    ops = split_operands(operand_text)
                    if len(ops) not in (2, 3):
                        raise AsmError(".comm requiere: simbolo, tamano[, alineacion]")
                    name = ops[0]
                    if not LABEL_RE.match(name):
                        raise AsmError(f"simbolo .comm invalido: {name}")
                    if name in label_offsets or name in equates:
                        raise AsmError(
                            f"label duplicado: {name} "
                            f"(ya definido en {label_origins[name]})"
                        )
                    if name in externs:
                        raise AsmError(
                            f"{name} ya es un simbolo .extern "
                            f"(declarado en {label_origins[name]})"
                        )
                    size = parse_int(ops[1])
                    alignment = parse_int(ops[2]) if len(ops) == 3 else 4
                    if size < 0:
                        raise AsmError(".comm no puede tener tamano negativo")
                    offsets[".bss"] = align_to(offsets[".bss"], alignment)
                    label_offsets[name] = (".bss", offsets[".bss"])
                    label_origins[name] = ubicacion(origin, number)
                    symbol_sources[name] = SourceLocation(origin, number)
                    comm_sizes[name] = size
                    offsets[".bss"] += size
                    continue

                size = directive_size_bytes(mnemonic, operand_text, offsets[section])
            except AsmError as error:
                raise AsmError(f"{ubicacion(origin, number)}: {error}") from None
            if size:
                lines.append(SourceLine(number, text, offsets[section], section,
                                        origin, size))
                offsets[section] += size
        else:
            size = instruction_size_bytes(text)
            if li_has_label(text):
                index = len(candidates)
                candidates.append(split_operands(text.split(None, 1)[1])[1])
                if shrunk is None or index in shrunk:
                    size = 4
            lines.append(SourceLine(number, text, offsets[section], section,
                                    origin, size))
            offsets[section] += size

    bases: dict[str, int] = {}
    pc = 0
    for name in SECTION_ORDER:
        pc = align_to(pc, 4)
        bases[name] = pc
        pc += offsets[name]
    image_size = align_to(pc, 4)

    labels = {
        name: bases[section_name] + offset
        for name, (section_name, offset) in label_offsets.items()
    }
    labels.update({name: 0 for name in externs})
    # Un solo espacio de nombres. Las colisiones ya se rechazaron en las dos
    # direcciones mas arriba, asi que aqui no puede pisarse nada.
    labels.update(equates)
    for name in sorted(globals_):
        if name not in labels:
            raise AsmError(f"simbolo .global sin definir: {name}")
    laid_out_lines = [
        SourceLine(line.number, line.text,
                   bases[line.section] + line.pc, line.section, line.origin,
                   line.size)
        for line in lines
    ]
    laid_out_lines.sort(key=lambda line: line.pc)

    # `equates` se devuelve aparte de `labels` ademas de fundido en el: quien
    # solo resuelve nombres quiere el espacio unico, pero el listado necesita
    # distinguir una constante de una etiqueta, y el nombre no lo dice.
    info = Layout(
        label_section={name: sec for name, (sec, _) in label_offsets.items()},
        comm_sizes=comm_sizes,
        section_base=bases,
        section_size=dict(offsets),
        symbol_sources=symbol_sources,
        externs=externs,
        globals=globals_,
    )
    return laid_out_lines, labels, image_size, equates, info, candidates


# ---------------------------------------------------------------------------
# Pass 2
# ---------------------------------------------------------------------------

def branch_offset(target_pc: int, current_pc: int, bits: int) -> int:
    """
    target = PC + 4 + offset * 4
    """
    delta = target_pc - (current_pc + 4)

    if delta % 4 != 0:
        raise AsmError("target de branch no alineado")

    offset = delta // 4
    return require_signed(offset, bits, "offset de branch")


def resolve_target(token: str, labels: dict[str, int]) -> int:
    token = token.strip()
    if token in labels:
        return labels[token]
    if "+" in token[1:] or "-" in token[1:]:
        parts = re.findall(r"[+-]?[^+-]+", token)
        if len(parts) > 1 and "".join(parts) == token:
            total = 0
            for part in parts:
                sign = 1
                if part[0] in "+-":
                    if part[0] == "-":
                        sign = -1
                    part = part[1:]
                total += sign * resolve_target(part, labels)
            return total
    if LABEL_RE.match(token) or "@" in token:
        # Parece un nombre, no un numero. Decir "entero invalido" mandaba a
        # buscar una errata en un literal que no existe; y con las etiquetas
        # locales el nombre que se veia era el compuesto, `drawline@loop`, que
        # no esta escrito en ningun sitio. Se muestra como lo escribio quien
        # lo escribio.
        global_, _, local = token.partition("@")
        visible = f"@{local} (local de {global_})" if local else token
        raise AsmError(f"etiqueta no definida: {visible}")
    return parse_int(token)


def assemble_instruction(line: SourceLine, labels: dict[str, int]) -> int:
    parts = line.text.split(None, 1)
    mnemonic = parts[0].upper()
    operand_text = parts[1] if len(parts) > 1 else ""
    ops = split_operands(operand_text)

    if mnemonic in {"LI", "LA"}:
        raise AsmError(
            f"{mnemonic} solo se puede usar como pseudoinstrucción completa")

    # RET no es un opcode: el enlace vive en R31 por convencion de llamada.
    if mnemonic == "RET":
        if ops:
            raise AsmError("RET no acepta operandos")
        mnemonic = "JR"
        ops = ["R31"]

    if mnemonic not in REAL_OPS:
        raise AsmError(f"instrucción desconocida: {mnemonic}")

    if mnemonic in NO_OPERAND_OPS:
        if ops:
            raise AsmError(f"{mnemonic} no acepta operandos")
        return encode_real(mnemonic)

    if mnemonic in R3_OPS:
        require_operands(mnemonic, ops, 3, "Rd, Ra, Rb")
        rd, ra, rb = map(parse_reg, ops)
        return encode_real(mnemonic, Rd=rd, Ra=ra, Rb=rb)

    if mnemonic in IMM5_OPS:
        require_operands(mnemonic, ops, 3, "Rd, Ra, imm5")
        rd = parse_reg(ops[0])
        ra = parse_reg(ops[1])
        amount = parse_int(ops[2])
        if not 0 <= amount <= 31:
            raise AsmError(
                f"cantidad de {mnemonic} fuera de rango 0..31: {amount}")
        return encode_real(mnemonic, Rd=rd, Ra=ra, imm5=amount)

    if mnemonic in GETID_OPS:
        require_operands(mnemonic, ops, 1, "Rd")
        return encode_real(mnemonic, Rd=parse_reg(ops[0]))

    if mnemonic in I2_OPS:
        require_operands(mnemonic, ops, 2, "Rd, imm16")
        rd = parse_reg(ops[0])
        imm = imm16_for(mnemonic, ops[1], labels)
        return encode_real(mnemonic, Rd=rd, imm16=imm)

    if mnemonic in I3_OPS:
        x, y, immediate_text = parse_i3_operands(mnemonic, ops)
        imm = imm16_for(mnemonic, immediate_text, labels)
        return encode_real(mnemonic, Rd=x, Ra=y, imm16=imm)

    if mnemonic in BRANCH_OPS:
        require_operands(mnemonic, ops, 3, "Ra, Rb, label")
        ra = parse_reg(ops[0])
        rb = parse_reg(ops[1])
        off = branch_word_offset(mnemonic, ops[2], line, labels)
        return encode_real(mnemonic, Ra=ra, Rb=rb, target=off)

    if mnemonic in B_TARGET_OPS:
        require_operands(mnemonic, ops, 1, "label")
        off = branch_word_offset(mnemonic, ops[0], line, labels)
        return encode_real(mnemonic, target=off)

    if mnemonic == "JAL":
        require_operands(mnemonic, ops, 2, "Rd, label")
        rd = parse_reg(ops[0])
        off = branch_word_offset(mnemonic, ops[1], line, labels)
        return encode_real(mnemonic, Rd=rd, target=off)

    if mnemonic == "JALR":
        require_operands(mnemonic, ops, 3, "Rd, Ra, imm16")
        rd = parse_reg(ops[0])
        ra = parse_reg(ops[1])
        imm = require_signed(parse_int(ops[2]), 16, "inmediato JALR")
        return encode_real(mnemonic, Rd=rd, Ra=ra, imm16=imm)

    if mnemonic == "JR":
        require_operands(mnemonic, ops, 1, "Ra")
        return encode_real(mnemonic, Ra=parse_reg(ops[0]))

    raise AsmError(f"{mnemonic}: encoding todavía no implementado")


def assemble_text(line: SourceLine, labels: dict[str, int]) -> bytes:
    parts = line.text.split(None, 1)
    mnemonic = parts[0].upper()
    operand_text = parts[1] if len(parts) > 1 else ""
    ops = split_operands(operand_text)

    if mnemonic in {"LI", "LA"}:
        if len(ops) != 2:
            raise AsmError(f"{mnemonic} requiere: Rd, expr32")
        rd = parse_reg(ops[0])
        if mnemonic == "LI" and line.size == 4:
            # Una palabra: lo que decidio la pasada 1 (`line.size`), no el
            # texto, porque un LI con etiqueta mide 4 u 8 segun adonde caiga.
            short = li_short_literal(operand_text)
            if short is None:
                short = resolve_target(ops[1], labels)
            if not LI_SHORT_MIN <= short <= LI_SHORT_MAX:
                raise AsmError(f"LI de una palabra con un valor que no cabe: {short}")
            if short < (1 << 15):
                word = encode_real("MOVI", Rd=rd, imm16=short)
            else:
                word = encode_real("ORI", Rd=rd, Ra=0, imm16=short)
            return word.to_bytes(4, "little")
        value = resolve_target(ops[1], labels) & 0xFFFFFFFF
        hi = (value >> 16) & 0xFFFF
        lo = value & 0xFFFF
        words = [
            encode_real("MOVHI", Rd=rd, imm16=hi),
            encode_real("ORI", Rd=rd, Ra=rd, imm16=lo),
        ]
        return b"".join(word.to_bytes(4, "little") for word in words)

    word = assemble_instruction(line, labels)
    return word.to_bytes(4, "little")


def emit_image(lines: list[SourceLine], labels: dict[str, int],
               image_size: int) -> bytes:
    image = bytearray()

    for line in lines:
        try:
            if line.pc < len(image):
                raise AsmError("solapamiento interno de secciones")
            if line.pc > len(image):
                image += b"\x00" * (line.pc - len(image))

            if is_directive(line.text):
                partes = line.text.split(None, 1)
                image += directive_bytes(
                    partes[0].upper(),
                    partes[1] if len(partes) > 1 else "", labels)
            else:
                image += assemble_text(line, labels)
        except AsmError as e:
            raise AsmError(
                f"{ubicacion(line.origin, line.number)}: {e}\n    {line.text}"
            ) from None

    if len(image) < image_size:
        image += b"\x00" * (image_size - len(image))
    while len(image) % 4:
        image += b"\x00"

    return bytes(image)


def line_kind(line: SourceLine) -> str:
    if is_directive(line.text):
        return "directive"
    mnemonic = line.text.split(None, 1)[0].upper()
    if mnemonic in {"LI", "LA", "RET"}:
        return "pseudo"
    return "instruction"


def build_sections(image: bytes, info: Layout) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    for name in SECTION_ORDER:
        base = info.section_base[name]
        size = info.section_size[name]
        sections[name] = Section(
            name=name,
            data=bytearray(image[base:base + size]),
            alignment=4,
            bss_size=size if name == ".bss" else 0,
        )
    return sections


def build_symbols(labels: dict[str, int], equates: dict[str, int],
                  info: Layout) -> dict[str, Symbol]:
    symbols: dict[str, Symbol] = {}
    for name, value in labels.items():
        if name in info.externs:
            symbols[name] = Symbol(
                name=name,
                section=None,
                offset=0,
                binding="global",
                source=info.symbol_sources.get(name),
                kind="extern",
                defined=False,
            )
            continue
        if name in equates:
            symbols[name] = Symbol(
                name=name,
                section=None,
                offset=value,
                binding="global" if name in info.globals else "local",
                source=info.symbol_sources.get(name),
                kind="absolute",
            )
            continue
        section = info.label_section[name]
        symbols[name] = Symbol(
            name=name,
            section=section,
            offset=value - info.section_base[section],
            binding="global" if name in info.globals else "local",
            source=info.symbol_sources.get(name),
            kind="comm" if name in info.comm_sizes else "label",
        )
    return symbols


def build_fragments(lines: list[SourceLine], image: bytes) -> list[Fragment]:
    fragments: list[Fragment] = []
    for line in lines:
        fragments.append(Fragment(
            section=line.section,
            offset=line.pc,
            size=line.size,
            source=line.location,
            text=line.text,
            kind=line_kind(line),
            data=image[line.pc:line.pc + line.size],
        ))
    return fragments


def build_address_to_source(lines: list[SourceLine]) -> dict[int, SourceLocation]:
    mapping: dict[int, SourceLocation] = {}
    for line in lines:
        for address in range(line.pc, line.pc + max(line.size, 1), 4):
            mapping[address] = line.location
    return mapping


def split_symbol_addend(token: str, labels: dict[str, int],
                        equates: dict[str, int]) -> Expression | None:
    """Return the single relocatable symbol in `token`, plus constant addend.

    The assembler still resolves everything eagerly for the flat image. This is
    metadata for object outputs, so we keep the accepted shape intentionally
    simple: one label, optionally plus/minus constants or `.equ` values.
    """
    token = token.strip()
    parts = re.findall(r"[+-]?[^+-]+", token)
    if not parts or "".join(parts) != token:
        parts = [token]

    symbol: str | None = None
    addend = 0
    for raw_part in parts:
        sign = 1
        part = raw_part.strip()
        if not part:
            continue
        if part[0] in "+-":
            if part[0] == "-":
                sign = -1
            part = part[1:].strip()
        if part in equates:
            addend += sign * equates[part]
            continue
        if part in labels:
            if sign < 0:
                return None
            if symbol is not None and symbol != part:
                return None
            symbol = part
            continue
        try:
            addend += sign * parse_int(part)
        except AsmError:
            return None

    if symbol is None:
        return None
    return Expression(symbol=symbol, addend=addend)


def relocation_from_expr(line: SourceLine, info: Layout, expr: Expression,
                         kind: str, *, byte_delta: int = 0,
                         bit_size: int = 32, mask: int | None = None,
                         addend_delta: int = 0) -> Relocation:
    if expr.symbol is None:
        raise AssertionError("relocation expression without symbol")
    if mask is None:
        mask = (1 << bit_size) - 1 if bit_size < 32 else 0xFFFFFFFF
    return Relocation(
        section=line.section,
        offset=line.pc - info.section_base[line.section] + byte_delta,
        symbol=expr.symbol,
        kind=kind,
        addend=expr.addend + addend_delta,
        source=line.location,
        resolved=True,
        bit_size=bit_size,
        mask=mask,
    )


def build_relocations(lines: list[SourceLine],
                      labels: dict[str, int],
                      equates: dict[str, int],
                      info: Layout) -> list[Relocation]:
    relocations: list[Relocation] = []
    for line in lines:
        parts = line.text.split(None, 1)
        mnemonic = parts[0].upper()
        operand_text = parts[1] if len(parts) > 1 else ""

        if is_directive(line.text):
            if mnemonic not in {".WORD", ".HALF", ".BYTE"}:
                continue
            bit_size = {".WORD": 32, ".HALF": 16, ".BYTE": 8}[mnemonic]
            byte_size = bit_size // 8
            for index, token in enumerate(split_operands(operand_text)):
                expr = split_symbol_addend(token, labels, equates)
                if expr is None:
                    continue
                relocations.append(relocation_from_expr(
                    line, info, expr, f"ABS{bit_size}",
                    byte_delta=index * byte_size,
                    bit_size=bit_size,
                ))
            continue

        ops = split_operands(operand_text)
        if mnemonic in {"LI", "LA"} and len(ops) == 2:
            expr = split_symbol_addend(ops[1], labels, equates)
            if expr is None:
                continue
            if line.size == 4:
                relocations.append(relocation_from_expr(
                    line, info, expr, "ABS16", bit_size=16))
            else:
                relocations.append(relocation_from_expr(
                    line, info, expr, "HI16", bit_size=16,
                    mask=0xFFFF0000))
                relocations.append(relocation_from_expr(
                    line, info, expr, "LO16", byte_delta=4,
                    bit_size=16, mask=0x0000FFFF))
            continue

        if mnemonic in I2_OPS and len(ops) == 2 and mnemonic != "MOVHI":
            expr = split_symbol_addend(ops[1], labels, equates)
            if expr is not None:
                relocations.append(relocation_from_expr(
                    line, info, expr, "ABS16", bit_size=16))
            continue

        if mnemonic in I3_OPS:
            try:
                _, _, immediate_text = parse_i3_operands(mnemonic, ops)
            except AsmError:
                continue
            expr = split_symbol_addend(immediate_text, labels, equates)
            if expr is not None:
                relocations.append(relocation_from_expr(
                    line, info, expr, "ABS16", bit_size=16))
            continue

        target_expr: Expression | None = None
        width = 0
        if mnemonic in BRANCH_OPS and len(ops) == 3:
            target_expr = split_symbol_addend(ops[2], labels, equates)
            width = target_width(mnemonic)
        elif mnemonic in B_TARGET_OPS and len(ops) == 1:
            target_expr = split_symbol_addend(ops[0], labels, equates)
            width = target_width(mnemonic)
        elif mnemonic == "JAL" and len(ops) == 2:
            target_expr = split_symbol_addend(ops[1], labels, equates)
            width = target_width(mnemonic)
        if target_expr is not None:
            relocations.append(relocation_from_expr(
                line, info, target_expr, "PCREL_WORD",
                bit_size=width,
                mask=((1 << width) - 1) << 2,
                addend_delta=-4,
            ))
    return relocations


def assemble_program(source: str, base_dir: Path | None = None,
                     origin: str = ENTRADA,
                     include_dirs: tuple[Path, ...] = (),
                     defines: frozenset[str] = frozenset()) -> AssemblyResult:
    """Assemble source and return binary plus internal assembly metadata."""
    lines, labels, image_size, equates, info = layout_pass(
        source, base_dir, origin, include_dirs, defines)
    image = emit_image(lines, labels, image_size)
    return AssemblyResult(
        sections=build_sections(image, info),
        symbols=build_symbols(labels, equates, info),
        relocations=build_relocations(lines, labels, equates, info),
        fragments=build_fragments(lines, image),
        image=image,
        address_to_source=build_address_to_source(lines),
    )


def assemble_bytes(source: str, base_dir: Path | None = None,
                   origin: str = ENTRADA,
                   include_dirs: tuple[Path, ...] = (),
                   defines: frozenset[str] = frozenset()) -> bytes:
    """`base_dir`, `origin` e `include_dirs` solo importan si el fuente usa
    `.include`: la carpeta del propio fichero, el nombre con el que citarlo en
    los errores, y las carpetas extra de busqueda. Ensamblar una cadena suelta
    sigue funcionando igual que antes de que existiera la directiva.
    `defines` son los simbolos de `-D` para `.ifdef`/`.ifndef`."""
    return assemble_program(source, base_dir, origin, include_dirs, defines).image


def assemble(source: str, base_dir: Path | None = None,
             origin: str = ENTRADA,
             include_dirs: tuple[Path, ...] = (),
             defines: frozenset[str] = frozenset()) -> list[int]:
    image = assemble_bytes(source, base_dir, origin, include_dirs, defines)
    return [
        int.from_bytes(image[index:index + 4], "little")
        for index in range(0, len(image), 4)
    ]


def load_program_bytes(path) -> bytes:
    """Carga un programa venga como venga: .asm, .hex o .bin.

    Vive aqui, y no en cada simulador, porque los tres la necesitan igual y
    tenerla repetida ya costo caro: `tools/README.md` documentaba
    `sim-gpu examples/vector.asm`, pero minigpu_sim.py hacia `read_bytes()` a
    secas y con un .asm delante fallaba con "el programa debe contener
    instrucciones completas" -- que describe el sintoma (el texto fuente no mide
    un multiplo de 4) y no la causa. minigpu_cycle.py si sabia ensamblar, asi
    que el mismo comando funcionaba o no segun el simulador.

    El mensaje de error nombra lo que se recibio: con un .asm que no compila,
    el AsmError sube tal cual y dice linea y motivo.
    """
    from pathlib import Path

    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".asm":
        # `t.tests/inc` se busca siempre, como en el depurador: es donde vive
        # `mmio.inc`, y sin esto un programa que lo incluye solo se podia
        # ensamblar desde el runner de tests o desde `mini-dbg`.
        shared = Path(__file__).resolve().parents[1] / "t.tests" / "inc"
        return assemble_bytes(path.read_text(encoding="utf-8"),
                              path.parent, path.name, (shared,))

    if suffix == ".hex":
        return read_hex_image(path)

    if suffix == ".bin":
        return path.read_bytes()

    raise ValueError(
        f"no se que hacer con '{path.name}': se esperaba .asm, .bin o .hex")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def default_output(source: Path) -> Path:
    """Donde va el .bin si no se da `-o`: `_build/` al lado del fuente.

    Antes era `<fuente>.bin` en la propia carpeta del caso, donde nada lo
    distinguia de un fichero de entrada (`.incbin`, `expected.bin`) y las
    carpetas acababan con binarios huerfanos."""
    return asm_output.default_output(source, ".bin")


def write_binary(image: bytes, path: Path) -> None:
    asm_output.write_binary_image(image, path)


def write_hex(image: bytes, path: Path) -> None:
    asm_output.write_hex_image(image, path)


def format_listing(source: str, base_dir: Path | None = None,
                   origin: str = ENTRADA,
                   include_dirs: tuple[Path, ...] = (),
                   defines: frozenset[str] = frozenset()) -> str:
    """Listado PC -> palabra -> fuente, mas la tabla de etiquetas.

    No es un desensamblador: no decodifica la imagen, sino que empareja cada
    linea del fuente ya expandido con el PC que le asigno la pasada 1 y con la
    palabra que salio de la 2. Para saber que hay en una direccion concreta
    -- tipicamente el `pc` que reporta la placa -- es lo mismo, y no obliga a
    mantener una tabla de decodificacion en paralelo a `isa.py`.
    """
    lines, labels, _, equates, info = layout_pass(
        source, base_dir, origin, include_dirs, defines)
    image = assemble_bytes(source, base_dir, origin, include_dirs, defines)

    # Las constantes de `.equ` comparten espacio de nombres con las etiquetas
    # pero no son posiciones del programa: anotarlas en el listado llenaria
    # cada PC de nombres de `mmio.inc` que no estan ahi.
    posiciones = {name: pc for name, pc in labels.items() if name not in equates}
    por_pc: dict[int, list[str]] = {}
    for name, pc in posiciones.items():
        por_pc.setdefault(pc, []).append(name)

    out: list[str] = []
    for line in lines:
        for name in sorted(por_pc.get(line.pc, [])):
            out.append(f"{line.pc:08x}            {name}:")
        trozo = image[line.pc:line.pc + 4]
        if len(trozo) == 4:
            word = f"{int.from_bytes(trozo, 'little'):08x}"
        else:
            word = "        "
        out.append(f"{line.pc:08x}  {word}  {line.text}")

    out.append("")
    out.append("Etiquetas:")
    for name, pc in sorted(posiciones.items(), key=lambda kv: (kv[1], kv[0])):
        out.append(f"  {pc:08x}  {name}")

    # Bloques para medir. Van después de `Etiquetas:` para no mover nada de lo
    # que ya lee quien consulta un PC: el listado antiguo es un prefijo de este.
    out.append("")
    out.append("Secciones:")
    for sec in SECTION_ORDER:
        base = info.section_base[sec]
        out.append(f"  {base:08x}  {info.section_size[sec]:08x}  {sec}")

    # Tamaño de un símbolo: el de `.comm` es exacto; el resto llega hasta la
    # siguiente etiqueta de su sección (o hasta el final de ella), así que
    # incluye el relleno de `.align`. El ensamblador no sabe qué etiquetas son
    # locales de una función —`.size` no existe—, y las lista todas.
    por_seccion: dict[str, list[int]] = {}
    for name in posiciones:
        por_seccion.setdefault(info.label_section[name], []).append(posiciones[name])
    out.append("")
    out.append("Simbolos:")
    for name, pc in sorted(posiciones.items(), key=lambda kv: (kv[1], kv[0])):
        sec = info.label_section[name]
        if name in info.comm_sizes:
            size = info.comm_sizes[name]
        else:
            fin = info.section_base[sec] + info.section_size[sec]
            size = min((p for p in por_seccion[sec] if p > pc), default=fin) - pc
        out.append(f"  {pc:08x}  {size:08x}  {sec:7s}  {name}")

    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniISA assembler v0.2")
    parser.add_argument("input", type=Path, help=".asm file to assemble")
    parser.add_argument("-o", "--output", type=Path,
                        help=".bin output file (by default _build/<name>.bin next to "
                             "the source: folder ignored by git, so that the "
                             "regenerable binary does not get confused with an input)")
    parser.add_argument("--hex", dest="hex_output", type=Path, help="hexadecimal textual output")
    parser.add_argument("--vobj", dest="vobj_output", type=Path,
                        help="VOBJ output file (with symbols and relocations)")
    parser.add_argument("--json", dest="json_output", type=Path,
                        help="JSON output file (with symbols and relocations)")
    parser.add_argument("-I", "--include-dir", type=Path, action="append", default=[],
                        metavar="FOLDER",
                        help="Where to look for .include files, in addition to the folder "
                             "of the source file (which is always checked first). "
                             "Can be repeated; they are tried in order")
    parser.add_argument("-D", "--define", action="append", default=[],
                        metavar="SYMBOL",
                        help="Defines a symbol for .ifdef/.ifndef. Can be "
                             "repeated")
    parser.add_argument("--listing", type=Path, nargs="?", const=Path("-"),
                        metavar="FILE",
                        help="Listing of PC / word / source and symbol table. "
                             "Without argument, it goes to the screen")
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8")

    try:
        defines = frozenset(parse_define_name(name) for name in args.define)
        result = assemble_program(source, args.input.parent, args.input.name,
                                  tuple(args.include_dir), defines)
    except AsmError as e:
        raise SystemExit(f"error: {e}")

    unresolved = [name for name, symbol in result.symbols.items()
                  if not symbol.defined]
    object_only = (args.vobj_output or args.json_output) and args.output is None
    output = args.output or default_output(args.input)
    wrote_bin = False
    if not object_only:
        if unresolved:
            names = ", ".join(sorted(unresolved))
            raise SystemExit(
                f"error: no puedo escribir .bin con simbolos externos sin resolver: {names}"
            )
        asm_output.write_output(result, output, "bin")
        wrote_bin = True

    if args.hex_output:
        if unresolved:
            names = ", ".join(sorted(unresolved))
            raise SystemExit(
                f"error: no puedo escribir .hex con simbolos externos sin resolver: {names}"
            )
        asm_output.write_output(result, args.hex_output, "hex")

    if args.vobj_output:
        asm_output.write_output(result, args.vobj_output, "vobj")

    if args.json_output:
        asm_output.write_output(result, args.json_output, "json")

    if args.listing:
        try:
            listing = format_listing(source, args.input.parent, args.input.name,
                                     tuple(args.include_dir), defines)
        except AsmError as e:                       # no deberia: ya ensamblo
            raise SystemExit(f"error: {e}")
        if str(args.listing) == "-":
            print(listing, end="")
        else:
            args.listing.write_text(listing, encoding="utf-8")

    if wrote_bin:
        print(f"{len(result.image) // 4} words -> {output}")
    elif args.vobj_output or args.json_output:
        targets = [str(path) for path in (args.vobj_output, args.json_output) if path]
        print(f"{len(result.image) // 4} words -> {', '.join(targets)}")


if __name__ == "__main__":
    main()
