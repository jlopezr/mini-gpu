"""Junta varios `.s` en uno solo, para que los pases vean el programa entero."""
from __future__ import annotations

import re

from .model import COMPILER_LOCAL_RE, SYMBOL_RE, OptError, directive_parts, parse_line

# Las etiquetas privadas del compilador: lcc numera `L.1`, `L.2`... desde 1 en cada compilacion, y
# `gen_softfloat.py` hace lo mismo con `__sf.n`. Al juntar dos `.s` se desplazan los numeros de la
# segunda para que no choquen: `L.k` pasa a `L.<k + desplazamiento>` y sigue siendo una `L.n` (el
# ensamblador las vuelve `L.<fichero>.<k>`, que `parse_unit` ya no reconoce como etiqueta de bloque).
NUMBERED_RE = re.compile(r"\b(L|__sf)\.(\d+)\b")


def split_strings(line: str) -> list[tuple[str, bool]]:
    """La linea en trozos (texto, es_cadena): lo que va entre comillas no se toca."""
    pieces: list[tuple[str, bool]] = []
    start, inside, escaped = 0, False, False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and inside:
            escaped = True
        elif char == '"':
            if inside:
                pieces.append((line[start:index + 1], True))
                start = index + 1
            else:
                pieces.append((line[start:index], False))
                start = index
            inside = not inside
    pieces.append((line[start:], inside))
    return pieces


def shift_labels(line: str, offsets: dict[str, int]) -> str:
    if not any(offsets.values()) or ("L." not in line and "__sf." not in line):
        return line
    return "".join(
        piece if is_string else
        NUMBERED_RE.sub(lambda m: f"{m.group(1)}.{int(m.group(2)) + offsets[m.group(1)]}", piece)
        for piece, is_string in split_strings(line))


def merge_sources(sources: list[tuple[str, str]]) -> str:
    """Une los `.s` `(ruta, texto)` en el orden dado. Una sola entrada se devuelve tal cual.

    Falla si dos unidades definen el mismo simbolo (una etiqueta o un `.comm`), como el ensamblador
    cuando las ve juntas. `.extern` repetidos no son un error. Cada unidad empieza en `.text`."""
    if len(sources) == 1:
        return sources[0][1]
    defined: dict[str, str] = {}
    offsets = {"L": 0, "__sf": 0}
    out: list[str] = []
    for path, text in sources:
        highest = dict(offsets)
        out.append(f"; ---- {path}\n.text")
        for raw in text.splitlines():
            line = shift_labels(raw, offsets)
            for found in NUMBERED_RE.finditer(raw):
                kind = found.group(1)
                highest[kind] = max(highest[kind], offsets[kind] + int(found.group(2)))
            for parsed in parse_line(line):
                if parsed.kind == "label" and not COMPILER_LOCAL_RE.match(parsed.name):
                    name = parsed.name
                elif parsed.kind == "directive" and parsed.text.split(None, 1)[0].lower() == ".comm":
                    name = directive_parts(parsed)[1]
                else:
                    continue
                if SYMBOL_RE.fullmatch(name) is None:
                    continue
                if name in defined and defined[name] != path:
                    raise OptError(f"simbolo '{name}' definido en {defined[name]} y en {path}")
                defined[name] = path
            out.append(line)
        offsets = highest
    return "\n".join(out) + "\n"
