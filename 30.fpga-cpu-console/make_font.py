"""Genera una imagen EBR de 256 glifos 8x16 con la asignacion CP437.

Los dos perfiles dan la misma asignacion de codigos (la de `text_console.v` y
la de `console_mini.c` de z.tui); solo cambia el dibujo:

  pc       todo desde Unscii-16 (`unscii-16.hex`, dominio publico).
  cpc464   texto desde CPC464-Mode1.ttf (8x8, cada fila duplicada a 8x16). El
           bloque 0xB0-0xDF (sombras, cajas simples/dobles/mixtas y bloques)
           sale de Unscii para que todas las uniones encajen entre si. Lo que
           la TTF no tiene tambien se completa desde Unscii.
  tamzen   igual, pero el texto sale de un BDF 8x16 (Tamzen8x16r.bdf, derivada
           de Tamsyn) sin duplicar filas. Solo trae Latin-1. Las cajas simples,
           dobles y mixtas (0xB3-0xDA) se generan con lineas de 1 px, y los
           punteros 0x10, 0x11, 0x1E y 0x1F se dibujan pequenos, para que
           encajen con su trazo fino; sombras y bloques siguen siendo de Unscii.

Cada glifo se dibuja con origen fijo, sin centrarlo por su caja: centrarlo
subia el `_` y bajaba el `.` hasta el medio de la celda.
"""
import argparse
import sys
from pathlib import Path

LOW = "☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"

# Glifos que ni Unscii ni la TTF traen. Ocho columnas por fila, 16 filas.
HAND = {
    0x263C: [  # ☼ (0x0F)
        "........", "........", "...##...", ".#.##.#.",
        "..####..", ".######.", "..####..", "#.####.#",
        "#.####.#", "..####..", ".######.", "..####..",
        ".#.##.#.", "...##...", "........", "........",
    ],
    0x2302: [  # ⌂ (0x7F)
        "........", "........", "........", "...##...",
        "..####..", ".##..##.", "##....##", "##....##",
        "##....##", "##....##", "##....##", "########",
        "........", "........", "........", "........",
    ],
    0x2310: [  # ⌐ (0xA9)
        "........", "........", "........", "........",
        "........", "........", "........", "########",
        "########", "......##", "......##", "......##",
        "........", "........", "........", "........",
    ],
    0x2219: [  # ∙ (0xF9)
        "........", "........", "........", "........",
        "........", "........", "........", "...##...",
        "...##...", "........", "........", "........",
        "........", "........", "........", "........",
    ],
}

# El 0x10/0x11 de CP437 son los punteros ► ◄; la TTF solo trae los triangulos.
TTF_ALIASES = {0x25BA: (0x25BA, 0x25B6), 0x25C4: (0x25C4, 0x25C0)}

BOX_BLOCK = range(0xB0, 0xE0)
BLANK = [0] * 16

# Cajas de 1 px para el perfil tamzen, centradas en el eje de su `+`: columna 4 y
# fila 7. Una linea simple es 1 px; una doble son dos lineas a cada lado del eje
# (columnas 3 y 5, filas 6 y 8) con 1 px de hueco. Codigo CP437:
# (arriba, abajo, izquierda, derecha), con 0 = nada, 1 = simple, 2 = doble.
THIN_BOX = {
    0xB3: (1, 1, 0, 0), 0xB4: (1, 1, 1, 0), 0xB5: (1, 1, 2, 0), 0xB6: (2, 2, 1, 0),
    0xB7: (0, 2, 1, 0), 0xB8: (0, 1, 2, 0), 0xB9: (2, 2, 2, 0), 0xBA: (2, 2, 0, 0),
    0xBB: (0, 2, 2, 0), 0xBC: (2, 0, 2, 0), 0xBD: (2, 0, 1, 0), 0xBE: (1, 0, 2, 0),
    0xBF: (0, 1, 1, 0), 0xC0: (1, 0, 0, 1), 0xC1: (1, 0, 1, 1), 0xC2: (0, 1, 1, 1),
    0xC3: (1, 1, 0, 1), 0xC4: (0, 0, 1, 1), 0xC5: (1, 1, 1, 1), 0xC6: (1, 1, 0, 2),
    0xC7: (2, 2, 0, 1), 0xC8: (2, 0, 0, 2), 0xC9: (0, 2, 0, 2), 0xCA: (2, 0, 2, 2),
    0xCB: (0, 2, 2, 2), 0xCC: (2, 2, 0, 2), 0xCD: (0, 0, 2, 2), 0xCE: (2, 2, 2, 2),
    0xCF: (1, 0, 2, 2), 0xD0: (2, 0, 1, 1), 0xD1: (0, 1, 2, 2), 0xD2: (0, 2, 1, 1),
    0xD3: (2, 0, 0, 1), 0xD4: (1, 0, 0, 2), 0xD5: (0, 1, 0, 2), 0xD6: (0, 2, 0, 1),
    0xD7: (2, 2, 1, 1), 0xD8: (1, 1, 2, 2), 0xD9: (1, 0, 1, 0), 0xDA: (0, 1, 0, 1),
}
V_LANES = {1: (4,), 2: (3, 5)}
H_LANES = {1: (7,), 2: (6, 8)}

# Punteros pequenos con la punta sobre los mismos ejes (0x10 ►, 0x11 ◄, 0x1E ▲, 0x1F ▼).
THIN_GLYPHS = {
    0x1E: ["........"] * 6 + ["....#...", "...###..", "..#####.", ".#######"] + ["........"] * 6,
    0x1F: ["........"] * 6 + [".#######", "..#####.", "...###..", "....#..."] + ["........"] * 6,
    0x10: ["........"] * 4 + ["..#.....", "..##....", "..###...", "..####..",
                              "..###...", "..##....", "..#....."] + ["........"] * 5,
    0x11: ["........"] * 4 + [".....#..", "....##..", "...###..", "..####..",
                              "...###..", "....##..", ".....#.."] + ["........"] * 5,
}


def thin_box(up, down, left, right):
    """Filas de un caracter de caja de 1 px; las reglas de union siguen las de Unscii."""
    grid = [[0] * 8 for _ in range(16)]

    def hline(y, x0, x1):
        for x in range(x0, x1 + 1):
            grid[y][x] = 1

    def vline(x, y0, y1):
        for y in range(y0, y1 + 1):
            grid[y][x] = 1

    sv, sh = max(up, down), max(left, right)
    through_v, through_h = bool(up and down), bool(left and right)
    verticals, horizontals = V_LANES.get(sv, ()), H_LANES.get(sh, ())

    if not sh:
        for x in verticals:
            vline(x, 0, 15)
    elif not sv:
        for y in horizontals:
            hline(y, 0, 7)
    else:
        def lane_end(arm_is_up, lane):
            # Fila en la que el carril se une a la horizontal.
            if through_h:
                return horizontals[0] if arm_is_up else horizontals[-1]
            near = verticals[0] if left else verticals[-1]
            outer = len(verticals) == 1 or lane != near
            if arm_is_up:
                return horizontals[-1] if outer else horizontals[0]
            return horizontals[0] if outer else horizontals[-1]

        if sv == 1 and through_v:
            vline(verticals[0], 0, 15)
        else:
            for lane in verticals:
                if up:
                    vline(lane, 0, lane_end(True, lane))
                if down:
                    vline(lane, lane_end(False, lane), 15)

        def meeting_column(on_left, row):
            near = verticals[0] if on_left else verticals[-1]
            far = verticals[-1] if on_left else verticals[0]
            if through_v:
                if sv == 1:
                    return verticals[0]
                return far if sh == 1 and through_h else near
            if sv == 1:
                return verticals[0]
            if sh == 1:
                return far
            upper = row == horizontals[0]
            return far if (upper if down else not upper) else near

        for row in horizontals:
            if left:
                hline(row, 0, meeting_column(True, row))
            if right:
                hline(row, meeting_column(False, row), 7)

    return [sum(bit << (7 - x) for x, bit in enumerate(line)) for line in grid]


def cp437_char(code):
    if code in (0x00, 0xFF):  # NUL y NBSP: en blanco
        return " "
    if 1 <= code <= 0x1F:
        return LOW[code - 1]
    if code == 0x7F:
        return "⌂"
    return bytes([code]).decode("cp437")


def load_unscii(path):
    glyphs = {}
    for line in path.read_text().splitlines():
        codepoint, data = line.strip().split(":")
        if len(data) == 32:  # los de 64 digitos son de doble ancho
            glyphs[int(codepoint, 16)] = list(bytes.fromhex(data))
    return glyphs


def hand_rows(rows):
    return [int(row.replace(".", "0").replace("#", "1"), 2) for row in rows]


def hand_glyph(codepoint):
    return hand_rows(HAND[codepoint])


class Ttf8x8:
    source = "ttf"

    def __init__(self, path):
        from PIL import ImageFont
        self.font = ImageFont.truetype(str(path), 8)
        self.tofu = self.render("￿")

    def render(self, char):
        from PIL import Image, ImageDraw
        image = Image.new("1", (8, 8), 0)
        ImageDraw.Draw(image).text((0, 0), char, font=self.font, fill=1)
        return [sum(int(image.getpixel((x, y)) != 0) << (7 - x) for x in range(8))
                for y in range(8)]

    def glyph(self, codepoint):
        """Filas 8x16 (cada fila de 8x8 duplicada) o None si la TTF no lo trae."""
        for candidate in TTF_ALIASES.get(codepoint, (codepoint,)):
            rows = self.render(chr(candidate))
            if rows != self.tofu and any(rows):
                return [row for row in rows for _ in (0, 1)]
        return None


class Bdf8x16:
    """Glifos de un BDF de celda 8x16, por punto de codigo (ISO8859-1 = Unicode)."""
    source = "bdf"

    def __init__(self, path):
        self.glyphs = {}
        ascent = encoding = bbox = rows = None
        for line in path.read_text().splitlines():
            parts = line.split()
            if not parts:
                continue
            key = parts[0]
            if key == "FONTBOUNDINGBOX":
                ascent = int(parts[2]) + int(parts[4])
            elif key == "ENCODING":
                encoding = int(parts[1])
            elif key == "BBX":
                bbox = tuple(int(value) for value in parts[1:5])
            elif key == "BITMAP":
                rows = []
            elif key == "ENDCHAR":
                if encoding is not None and encoding >= 0 and rows:
                    self.glyphs[encoding] = self._place(rows, bbox, ascent)
                encoding = bbox = rows = None
            elif rows is not None:
                rows.append(int(key, 16))

    @staticmethod
    def _place(rows, bbox, ascent):
        _, height, x_offset, y_offset = bbox
        top = ascent - (y_offset + height)
        cell = [0] * 16
        for index, byte in enumerate(rows):
            if 0 <= top + index < 16:
                cell[top + index] = (byte >> x_offset if x_offset >= 0 else byte << -x_offset) & 0xFF
        return cell

    def glyph(self, codepoint):
        return self.glyphs.get(codepoint)


def build(profile, unscii, primary):
    rows, origin = [], []
    for code in range(256):
        codepoint = ord(cp437_char(code))
        glyph, source = None, None
        if codepoint == 0x20:
            glyph, source = BLANK, "blank"
        elif profile == "tamzen" and code in THIN_BOX:
            glyph, source = thin_box(*THIN_BOX[code]), "thin"
        elif profile == "tamzen" and code in THIN_GLYPHS:
            glyph, source = hand_rows(THIN_GLYPHS[code]), "thin"
        elif primary is not None and code not in BOX_BLOCK:
            glyph = primary.glyph(codepoint)
            source = primary.source
        if glyph is None and codepoint in unscii:
            glyph, source = unscii[codepoint], "unscii"
        if glyph is None and codepoint in HAND:
            glyph, source = hand_glyph(codepoint), "hand"
        if glyph is None:
            sys.exit(f"sin glifo para el codigo {code:#04x} (U+{codepoint:04X})")
        origin.append(source)
        rows.append(sum(byte << (8 * y) for y, byte in enumerate(glyph)))
    return rows, origin


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=("pc", "cpc464", "tamzen"), default="pc")
    parser.add_argument("--unscii", type=Path, required=True)
    parser.add_argument("--ttf", type=Path)
    parser.add_argument("--bdf", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.profile == "cpc464" and not args.ttf:
        parser.error("--profile cpc464 necesita --ttf")
    if args.profile == "tamzen" and not args.bdf:
        parser.error("--profile tamzen necesita --bdf")

    primary = {"pc": None,
               "cpc464": lambda: Ttf8x8(args.ttf),
               "tamzen": lambda: Bdf8x16(args.bdf)}[args.profile]
    rows, origin = build(args.profile, load_unscii(args.unscii), primary and primary())

    output = args.output or Path(f"fonts/font8x16_{args.profile}.hex")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(f"{packed:032x}" for packed in rows) + "\n")

    for source in ("ttf", "bdf", "thin", "unscii", "hand", "blank"):
        codes = [f"{c:02X}" for c, s in enumerate(origin) if s == source]
        if codes:
            print(f"{source:7} {len(codes):3}", " ".join(codes) if len(codes) < 60 else "")


if __name__ == "__main__":
    main()
