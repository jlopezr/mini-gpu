#!/usr/bin/env python3
"""
MiniISA assembler v0.1

Sintaxis inicial:
    ADD   R1, R2, R3
    ADDI  R1, R2, -4
    MOVI  R1, 123
    MOVHI R1, 0x1234
    SHLI  R1, R2, 5     ; tambien SHRI y SARI; cantidad inmediata 0..31
    MULHI R1, R2, R3    ; parte alta signed; DIVU, REM y REMU tambien
    LOAD  R1, R2, 16
    STORE R1, R2, 16

    BEQ   R1, R2, label
    BLT   R1, R2, label
    BRA   label

    SLT   R1, R2, R3   ; comparaciones materializadas; SLTU tambien

    JAL   R31, funcion
    JALR  R31, R5, 0
    JR    R5
    RET               ; alias de JR R31

    GETTID R1
    NOP
    HALT

Comentarios:
    ; comentario
    # comentario

Labels:
    loop:
        ...
        BRA loop

Inclusion de otros ficheros:
    .include "drawline.inc"
    .once                   ; al principio del INCLUIDO: no entra dos veces

    Se busca primero en la carpeta del fichero que incluye, y despues en las
    carpetas pasadas con `-I` (repetible). La biblioteca compartida del repo
    esta en `x.tests/inc`, y los lanzadores ya la pasan. No hay espacios de
    nombres: las etiquetas de lo incluido son globales, y un choque se
    denuncia diciendo los dos sitios.

    `.once` lo pone el fichero incluido, no quien lo incluye: ser idempotente
    es una propiedad suya, y asi no hay que acordarse en cada llamada. Es lo
    que permite que un .inc arrastre sus dependencias. Sin `.once`, incluir
    dos veces emite el contenido dos veces, que a veces es lo que se quiere.

Salida:
    binario little-endian, una palabra de 32 bits por instrucción.
"""

from __future__ import annotations

import argparse
import re
import struct
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# ISA
# ---------------------------------------------------------------------------

OPCODES = {
    # ALU
    "NOP":    0x00,
    "ADD":    0x01,
    "SUB":    0x02,
    "MULFX":  0x03,
    "AND":    0x04,
    "OR":     0x05,
    "XOR":    0x06,
    "SHL":    0x07,
    "SHR":    0x08,
    "SAR":    0x09,
    "MUL":    0x0A,
    "MULHI":  0x0B,
    "DIV":    0x0C,
    "DIVU":   0x0D,
    "REM":    0x0E,
    "REMU":   0x0F,

    # Immediate / memory
    "MOVI":   0x10,
    "ADDI":   0x11,
    "ANDI":   0x12,
    "ORI":    0x13,
    "XORI":   0x14,
    "LOAD":   0x15,
    "STORE":  0x16,
    "MOVHI":  0x17,

    # Accesos sub-palabra. Mapa de propuesta-v0.2.md §7; v0.3 reordena
    # 0x1A..0x1D, asi que estos valores cambiaran al migrar.
    "LOADB":  0x18,
    "LOADUB": 0x19,
    "STOREB": 0x1A,
    "LOADH":  0x1B,
    "LOADUH": 0x1C,
    "STOREH": 0x1D,

    # Control
    "BEQ":    0x20,
    "BNE":    0x21,
    "BLT":    0x22,
    "BGE":    0x23,
    "BLTU":   0x24,
    "BGEU":   0x25,

    # Comparaciones materializadas. R-Type, capability `compare`.
    "SLT":    0x26,
    "SLTU":   0x27,

    # Llamadas y saltos indirectos. Mapa de propuesta-v0.2.md §3.2: R0 sigue
    # siendo un registro general, asi que JR gasta opcode propio.
    "JAL":    0x2C,
    "JALR":   0x2D,
    "JR":     0x2E,

    "BRA":    0x2F,

    # System / SIMT
    "GETTID": 0x30,
    "SSY":    0x31,
    "BAR":    0x32,
    "EXIT":   0x33,
    "TRAP":   0x3E,
    "HALT":   0x3F,
}

R3_OPS = {
    "ADD", "SUB", "MULFX", "AND", "OR", "XOR",
    "SHL", "SHR", "SAR",
    "MUL", "MULHI", "DIV", "DIVU", "REM", "REMU",
    "SLT", "SLTU",
}

# Desplazamientos con cantidad inmediata: opcion B de propuesta-v0.2.md §4.2.
# No gastan opcode. Reusan el de su version con registro y encienden el bit 10
# del campo `extra`; la cantidad viaja en los cinco bits del campo Rb.
#
#   31       26 25   21 20   16 15   11 10  9         0
#   [ opcode ][  Rd  ][  Ra  ][ imm5 ][ 1 ][    0     ]
#
# Consecuencia: para 0x07..0x09 el campo reservado ya no es `extra` entero sino
# `extra[9:0]`, e `instruction[10]` pasa a ser significativo.
SHIFT_IMMEDIATE_BIT = 1 << 10

SHIFT_IMM_OPS = {
    "SHLI": "SHL",
    "SHRI": "SHR",
    "SARI": "SAR",
}

I3_SIGNED_OPS = {
    "ADDI", "LOAD", "STORE",
    "LOADB", "LOADUB", "STOREB", "LOADH", "LOADUH", "STOREH",
}

I3_UNSIGNED_OPS = {
    "ANDI", "ORI", "XORI",
}

BRANCH_OPS = {
    "BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU",
}


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


@dataclass
class SourceLine:
    number: int
    text: str
    pc: int
    section: str = ".text"
    origin: str = ENTRADA


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


def instruction_size_bytes(text: str) -> int:
    parts = text.split(None, 1)
    mnemonic = parts[0].upper()
    if mnemonic in {"LI", "LA"}:
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


def expand_includes(source: str, base_dir: Path | None = None,
                    origin: str = ENTRADA,
                    include_dirs: tuple[Path, ...] = (),
                    _stack: tuple[Path, ...] = (),
                    _once: set[Path] | None = None) -> list[tuple[str, int, str]]:
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

    for number, raw in enumerate(source.splitlines(), 1):
        text = strip_comment(raw)
        if not text or not is_directive(text):
            filas.append((origin, number, raw))
            continue

        partes = text.split(None, 1)
        mnemonic = partes[0].upper()

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
            filas.append((origin, number, raw))
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
        filas.extend(expand_includes(
            incluido, resuelto.parent, resuelto.name,
            include_dirs, _stack + (resuelto,), _once
        ))

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


def encode_r(opcode: int, rd: int = 0, ra: int = 0, rb: int = 0, extra: int = 0) -> int:
    return (
        ((opcode & 0x3F) << 26)
        | ((rd & 0x1F) << 21)
        | ((ra & 0x1F) << 16)
        | ((rb & 0x1F) << 11)
        | (extra & 0x7FF)
    )


def encode_i(opcode: int, x: int = 0, y: int = 0, imm16: int = 0) -> int:
    return (
        ((opcode & 0x3F) << 26)
        | ((x & 0x1F) << 21)
        | ((y & 0x1F) << 16)
        | (imm16 & 0xFFFF)
    )


def encode_b(opcode: int, offset26: int = 0) -> int:
    return ((opcode & 0x3F) << 26) | (offset26 & 0x03FFFFFF)


# ---------------------------------------------------------------------------
# Pass 1
# ---------------------------------------------------------------------------

def first_pass(source: str,
               base_dir: Path | None = None,
               origin: str = ENTRADA,
               include_dirs: tuple[Path, ...] = (),
               ) -> tuple[list[SourceLine], dict[str, int], int, dict[str, int]]:
    label_offsets: dict[str, tuple[str, int]] = {}
    label_origins: dict[str, str] = {}
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

    for origin, number, raw in expand_includes(source, base_dir, origin, include_dirs):
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
                    size = parse_int(ops[1])
                    alignment = parse_int(ops[2]) if len(ops) == 3 else 4
                    if size < 0:
                        raise AsmError(".comm no puede tener tamano negativo")
                    offsets[".bss"] = align_to(offsets[".bss"], alignment)
                    label_offsets[name] = (".bss", offsets[".bss"])
                    label_origins[name] = ubicacion(origin, number)
                    offsets[".bss"] += size
                    continue

                size = directive_size_bytes(mnemonic, operand_text, offsets[section])
            except AsmError as error:
                raise AsmError(f"{ubicacion(origin, number)}: {error}") from None
            if size:
                lines.append(SourceLine(number, text, offsets[section], section, origin))
                offsets[section] += size
        else:
            lines.append(SourceLine(number, text, offsets[section], section, origin))
            offsets[section] += instruction_size_bytes(text)

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
    # Un solo espacio de nombres. Las colisiones ya se rechazaron en las dos
    # direcciones mas arriba, asi que aqui no puede pisarse nada.
    labels.update(equates)
    laid_out_lines = [
        SourceLine(line.number, line.text,
                   bases[line.section] + line.pc, line.section, line.origin)
        for line in lines
    ]
    laid_out_lines.sort(key=lambda line: line.pc)

    # `equates` se devuelve aparte de `labels` ademas de fundido en el: quien
    # solo resuelve nombres quiere el espacio unico, pero el listado necesita
    # distinguir una constante de una etiqueta, y el nombre no lo dice.
    return laid_out_lines, labels, image_size, equates


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
    return check_signed(offset, bits, "offset de branch")


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

    # SHLI/SHRI/SARI no tienen entrada propia en OPCODES: son el mismo opcode
    # que SHL/SHR/SAR con el bit de inmediato puesto.
    if mnemonic in SHIFT_IMM_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: Rd, Ra, imm5")
        rd = parse_reg(ops[0])
        ra = parse_reg(ops[1])
        amount = parse_int(ops[2])
        if not 0 <= amount <= 31:
            raise AsmError(
                f"cantidad de {mnemonic} fuera de rango 0..31: {amount}")
        return encode_r(OPCODES[SHIFT_IMM_OPS[mnemonic]], rd, ra, amount,
                        SHIFT_IMMEDIATE_BIT)

    if mnemonic not in OPCODES:
        raise AsmError(f"instrucción desconocida: {mnemonic}")

    opcode = OPCODES[mnemonic]

    # -------------------------------------------------------
    # No operands
    # -------------------------------------------------------

    if mnemonic in {"NOP", "BAR", "EXIT", "TRAP", "HALT"}:
        if ops:
            raise AsmError(f"{mnemonic} no acepta operandos")
        return encode_r(opcode)

    # -------------------------------------------------------
    # R-type: OP Rd, Ra, Rb
    # -------------------------------------------------------

    if mnemonic in R3_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: Rd, Ra, Rb")
        rd, ra, rb = map(parse_reg, ops)
        return encode_r(opcode, rd, ra, rb)

    # -------------------------------------------------------
    # MOVI / MOVHI
    # -------------------------------------------------------

    if mnemonic == "MOVI":
        if len(ops) != 2:
            raise AsmError("MOVI requiere: Rd, imm16")
        rd = parse_reg(ops[0])
        # Admite una etiqueta, y entonces el inmediato es su DIRECCION. Es como
        # un programa carga el puntero de una tabla o de un mensaje. Solo vale
        # mientras el programa quepa en los 32 KiB que alcanza un signed16; mas
        # alla, MOVHI + ORI.
        imm = check_signed(resolve_target(ops[1], labels), 16, "inmediato MOVI")
        return encode_i(opcode, rd, 0, imm)

    if mnemonic == "MOVHI":
        if len(ops) != 2:
            raise AsmError("MOVHI requiere: Rd, imm16")
        rd = parse_reg(ops[0])
        imm = check_unsigned(parse_int(ops[1]), 16, "inmediato MOVHI")
        return encode_i(opcode, rd, 0, imm)

    # -------------------------------------------------------
    # I-type: OP X, Y, imm16
    # -------------------------------------------------------

    if mnemonic in I3_SIGNED_OPS:
        if len(ops) == 2 and mnemonic in {
            "LOAD", "STORE",
            "LOADB", "LOADUB", "STOREB", "LOADH", "LOADUH", "STOREH",
        }:
            match = MEMORY_RE.match(ops[1])
            if not match:
                raise AsmError(f"{mnemonic} requiere: X, Y, imm16")
            x = parse_reg(ops[0])
            y = parse_reg(match.group(2))
            imm = check_signed(resolve_target(match.group(1), labels), 16,
                               f"inmediato {mnemonic}")
        else:
            if len(ops) != 3:
                raise AsmError(f"{mnemonic} requiere: X, Y, imm16")
            x = parse_reg(ops[0])
            y = parse_reg(ops[1])
            imm = check_signed(resolve_target(ops[2], labels), 16,
                               f"inmediato {mnemonic}")
        return encode_i(opcode, x, y, imm)

    if mnemonic in I3_UNSIGNED_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: X, Y, imm16")
        x = parse_reg(ops[0])
        y = parse_reg(ops[1])
        imm = check_unsigned(parse_int(ops[2]), 16, f"inmediato {mnemonic}")
        return encode_i(opcode, x, y, imm)

    # -------------------------------------------------------
    # Conditional branches: OP Ra, Rb, label
    # -------------------------------------------------------

    if mnemonic in BRANCH_OPS:
        if len(ops) != 3:
            raise AsmError(f"{mnemonic} requiere: Ra, Rb, label")
        ra = parse_reg(ops[0])
        rb = parse_reg(ops[1])
        target_pc = resolve_target(ops[2], labels)
        off = branch_offset(target_pc, line.pc, 16)
        return encode_i(opcode, ra, rb, off)

    # -------------------------------------------------------
    # BRA label
    # -------------------------------------------------------

    if mnemonic in {"BRA", "SSY"}:
        if len(ops) != 1:
            raise AsmError(f"{mnemonic} requiere: label")
        target_pc = resolve_target(ops[0], labels)
        off = branch_offset(target_pc, line.pc, 26)
        return encode_b(opcode, off)

    # -------------------------------------------------------
    # Llamadas y saltos indirectos
    #
    #   JAL  Rd, label      X = Rd, Y = 0,  imm16 = offset en palabras
    #   JALR Rd, Ra, imm16  X = Rd, Y = Ra, imm16 en palabras
    #   JR   Ra             X = 0,  Y = Ra, imm16 = 0
    #
    # RET es un alias de JR R31, no un opcode.
    # -------------------------------------------------------

    if mnemonic == "JAL":
        if len(ops) != 2:
            raise AsmError("JAL requiere: Rd, label")
        rd = parse_reg(ops[0])
        target_pc = resolve_target(ops[1], labels)
        off = branch_offset(target_pc, line.pc, 16)
        return encode_i(opcode, rd, 0, off)

    if mnemonic == "JALR":
        if len(ops) != 3:
            raise AsmError("JALR requiere: Rd, Ra, imm16")
        rd = parse_reg(ops[0])
        ra = parse_reg(ops[1])
        imm = check_signed(parse_int(ops[2]), 16, "inmediato JALR")
        return encode_i(opcode, rd, ra, imm)

    if mnemonic == "JR":
        if len(ops) != 1:
            raise AsmError("JR requiere: Ra")
        ra = parse_reg(ops[0])
        return encode_i(opcode, 0, ra, 0)

    # -------------------------------------------------------
    # GETTID Rd
    # -------------------------------------------------------

    if mnemonic == "GETTID":
        if len(ops) != 1:
            raise AsmError("GETTID requiere: Rd")
        rd = parse_reg(ops[0])
        return encode_i(opcode, rd, 0, 0)

    # -------------------------------------------------------
    # SSY label
    # -------------------------------------------------------

    if mnemonic == "SSY":
        if len(ops) != 1:
            raise AsmError("SSY requiere: label")
        target_pc = resolve_target(ops[0], labels)
        off = branch_offset(target_pc, line.pc, 26)
        return encode_b(opcode, off)

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
        value = resolve_target(ops[1], labels) & 0xFFFFFFFF
        hi = (value >> 16) & 0xFFFF
        lo = value & 0xFFFF
        words = [
            encode_i(OPCODES["MOVHI"], rd, 0, hi),
            encode_i(OPCODES["ORI"], rd, rd, lo),
        ]
        return b"".join(word.to_bytes(4, "little") for word in words)

    word = assemble_instruction(line, labels)
    return word.to_bytes(4, "little")

def assemble_bytes(source: str, base_dir: Path | None = None,
                   origin: str = ENTRADA,
                   include_dirs: tuple[Path, ...] = ()) -> bytes:
    """`base_dir`, `origin` e `include_dirs` solo importan si el fuente usa
    `.include`: la carpeta del propio fichero, el nombre con el que citarlo en
    los errores, y las carpetas extra de busqueda. Ensamblar una cadena suelta
    sigue funcionando igual que antes de que existiera la directiva."""
    lines, labels, image_size, _ = first_pass(source, base_dir, origin, include_dirs)
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


def assemble(source: str, base_dir: Path | None = None,
             origin: str = ENTRADA,
             include_dirs: tuple[Path, ...] = ()) -> list[int]:
    image = assemble_bytes(source, base_dir, origin, include_dirs)
    return [
        int.from_bytes(image[index:index + 4], "little")
        for index in range(0, len(image), 4)
    ]


def load_program_bytes(path) -> bytes:
    """Carga un programa venga como venga: .asm, .hex o .bin.

    Vive aqui, y no en cada simulador, porque los tres la necesitan igual y
    tenerla repetida ya costo caro: `tools/README.md` documentaba
    `gpusim examples/vector.asm`, pero minigpu_sim.py hacia `read_bytes()` a
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
        return assemble_bytes(path.read_text(encoding="utf-8"),
                              path.parent, path.name)

    if suffix == ".hex":
        return read_hex_image(path)

    if suffix == ".bin":
        return path.read_bytes()

    raise ValueError(
        f"no se que hacer con '{path.name}': se esperaba .asm, .bin o .hex")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_binary(image: bytes, path: Path) -> None:
    with path.open("wb") as f:
        f.write(image)


def write_hex(image: bytes, path: Path) -> None:
    with path.open("w", encoding="ascii") as f:
        for index in range(0, len(image), 4):
            word = int.from_bytes(image[index:index + 4], "little")
            f.write(f"{word:08X}\n")


def format_listing(source: str, base_dir: Path | None = None,
                   origin: str = ENTRADA,
                   include_dirs: tuple[Path, ...] = ()) -> str:
    """Listado PC -> palabra -> fuente, mas la tabla de etiquetas.

    No es un desensamblador: no decodifica la imagen, sino que empareja cada
    linea del fuente ya expandido con el PC que le asigno la pasada 1 y con la
    palabra que salio de la 2. Para saber que hay en una direccion concreta
    -- tipicamente el `pc` que reporta la placa -- es lo mismo, y no obliga a
    mantener una tabla de decodificacion en paralelo a `OPCODES`.
    """
    lines, labels, _, equates = first_pass(source, base_dir, origin, include_dirs)
    image = assemble_bytes(source, base_dir, origin, include_dirs)

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

    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniISA assembler v0.1")
    parser.add_argument("input", type=Path, help="fichero .asm")
    parser.add_argument("-o", "--output", type=Path, help="salida .bin")
    parser.add_argument("--hex", dest="hex_output", type=Path, help="salida hexadecimal textual")
    parser.add_argument("-I", "--include-dir", type=Path, action="append", default=[],
                        metavar="CARPETA",
                        help="donde buscar los .include, ademas de la carpeta "
                             "del propio fuente (que se mira siempre primero). "
                             "Se puede repetir; se prueban en orden")
    parser.add_argument("--listing", type=Path, nargs="?", const=Path("-"),
                        metavar="FICHERO",
                        help="listado PC / palabra / fuente y tabla de "
                             "etiquetas. Sin argumento sale por pantalla")
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8")

    try:
        image = assemble_bytes(source, args.input.parent, args.input.name,
                               tuple(args.include_dir))
    except AsmError as e:
        raise SystemExit(f"error: {e}")

    output = args.output or args.input.with_suffix(".bin")
    write_binary(image, output)

    if args.hex_output:
        write_hex(image, args.hex_output)

    if args.listing:
        try:
            listing = format_listing(source, args.input.parent, args.input.name,
                                     tuple(args.include_dir))
        except AsmError as e:                       # no deberia: ya ensamblo
            raise SystemExit(f"error: {e}")
        if str(args.listing) == "-":
            print(listing, end="")
        else:
            args.listing.write_text(listing, encoding="utf-8")

    print(f"{len(image) // 4} palabras -> {output}")


if __name__ == "__main__":
    main()
