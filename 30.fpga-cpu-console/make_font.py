"""Genera una imagen EBR de 256 glifos 8x16 con la asignacion CP437.

Los dos perfiles dan la misma asignacion de codigos (la de `text_console.v` y
la de `console_mini.c` de z.tui); solo cambia el dibujo:

  pc       todo desde Unscii-16 (`unscii-16.hex`, dominio publico).
  cpc464   texto desde CPC464-Mode1.ttf (8x8, cada fila duplicada a 8x16). El
           bloque 0xB0-0xDF (sombras, cajas simples/dobles/mixtas y bloques)
           sale de Unscii para que todas las uniones encajen entre si. Lo que
           la TTF no tiene tambien se completa desde Unscii.

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


def hand_glyph(codepoint):
    return [int(row.replace(".", "0").replace("#", "1"), 2) for row in HAND[codepoint]]


class Ttf8x8:
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


def build(profile, unscii, ttf):
    rows, origin = [], []
    for code in range(256):
        codepoint = ord(cp437_char(code))
        glyph, source = None, None
        if codepoint == 0x20:
            glyph, source = BLANK, "blank"
        elif profile == "cpc464" and code not in BOX_BLOCK:
            glyph = ttf.glyph(codepoint)
            source = "ttf"
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
    parser.add_argument("--profile", choices=("pc", "cpc464"), default="pc")
    parser.add_argument("--unscii", type=Path, required=True)
    parser.add_argument("--ttf", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.profile == "cpc464" and not args.ttf:
        parser.error("--profile cpc464 necesita --ttf")

    ttf = Ttf8x8(args.ttf) if args.profile == "cpc464" else None
    rows, origin = build(args.profile, load_unscii(args.unscii), ttf)

    output = args.output or Path(f"fonts/font8x16_{args.profile}.hex")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(f"{packed:032x}" for packed in rows) + "\n")

    for source in ("ttf", "unscii", "hand", "blank"):
        codes = [f"{c:02X}" for c, s in enumerate(origin) if s == source]
        if codes:
            print(f"{source:7} {len(codes):3}", " ".join(codes) if len(codes) < 60 else "")


if __name__ == "__main__":
    main()
