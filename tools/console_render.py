"""Dibuja la consola de texto 80x30 del simulador con una fuente `.hex` de 8x16.

El simulador guarda la consola como estado (RAM de texto y paleta) y no tiene
fuente: nada la compone sobre el framebuffer, que `--frame-output` y
`fb_window` muestran solo. Esto hace lo que hace `text_console.v`: celda
`BG[15:12] | FG[11:8] | CHAR[7:0]`, glifo de 8x16 con la fila 0 en el byte bajo,
colores 1..15 de la paleta y **el color 0 transparente**, que deja ver lo de
debajo. Sin framebuffer debajo, lo transparente sale negro.

Imagen de 640x480; el framebuffer de 320x240 se escala 2x, como el scanout.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

COLUMNS, ROWS = 80, 30
CELL_W, CELL_H = 8, 16
WIDTH, HEIGHT = COLUMNS * CELL_W, ROWS * CELL_H
FB_WIDTH, FB_HEIGHT = 320, 240
GLYPHS = 256


def load_font(path: Path) -> list[int]:
    words = [int(token, 16) for token in Path(path).read_text().split()]
    if len(words) != GLYPHS:
        raise ValueError(f"{Path(path).name}: {len(words)} glifos, se esperaban {GLYPHS}")
    return words


def _rgb565(value: int) -> tuple[int, int, int]:
    r, g, b = (value >> 11) & 0x1F, (value >> 5) & 0x3F, value & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _background(framebuffer: bytes | None) -> bytearray:
    """RGB888 de 640x480: el framebuffer RGB565 little-endian escalado 2x, o negro."""
    rgb = bytearray(WIDTH * HEIGHT * 3)
    if framebuffer is None or len(framebuffer) < FB_WIDTH * FB_HEIGHT * 2:
        return rgb
    for y in range(FB_HEIGHT):
        row = bytearray()
        for x in range(FB_WIDTH):
            offset = 2 * (y * FB_WIDTH + x)
            pixel = bytes(_rgb565(framebuffer[offset] | (framebuffer[offset + 1] << 8)))
            row += pixel * 2
        start = 2 * y * WIDTH * 3
        rgb[start:start + len(row)] = row
        rgb[start + len(row):start + 2 * len(row)] = row
    return rgb


def render_rgb(text_ram: list[int], palette: list[int], font: list[int],
               framebuffer: bytes | None = None) -> bytes:
    """Pantalla como RGB888 de 640x480."""
    rgb = _background(framebuffer)
    colors = [None] + [bytes(((palette[i] >> 16) & 0xFF, (palette[i] >> 8) & 0xFF, palette[i] & 0xFF))
                       for i in range(1, 16)]
    for cell_index, cell in enumerate(text_ram[:COLUMNS * ROWS]):
        glyph = font[cell & 0xFF]
        fg, bg = colors[(cell >> 8) & 0xF], colors[(cell >> 12) & 0xF]
        x0, y0 = (cell_index % COLUMNS) * CELL_W, (cell_index // COLUMNS) * CELL_H
        for y in range(CELL_H):
            bits = (glyph >> (8 * y)) & 0xFF
            base = ((y0 + y) * WIDTH + x0) * 3
            for x in range(CELL_W):
                color = fg if bits & (0x80 >> x) else bg
                if color is not None:  # color 0: transparente
                    rgb[base + 3 * x:base + 3 * x + 3] = color
    return bytes(rgb)


def write_png(path: Path, rgb: bytes, width: int = WIDTH, height: int = HEIGHT) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))
