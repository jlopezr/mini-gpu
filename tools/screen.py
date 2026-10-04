"""Lo que sale por la pantalla de un simulador: framebuffer, consola o los dos.

`snapshot(machine)` recoge del simulador lo mínimo para dibujar un frame
--modo de `VIDEO_CTRL`, el framebuffer frontal, y texto y paleta si la consola
está activa-- y `Compositor` lo compone en una imagen de 640x480. Es el mismo
dibujo que `console_render.render_rgb`, que sigue siendo la referencia y la que
usan las imágenes de `--console-image`, pero con PIL y con teselas en caché:
`render_rgb` recorre 300 000 píxeles en Python y no sirve para una ventana viva.

Qué se ve, según el contrato de VIDEO (`1.isa/mmio.md` §9):

    BLANK     negro
    PATTERN   barras de color (en el hardware es la prueba de HDMI)
    SCANOUT   el framebuffer frontal, escalado 2x

y, con consola (`VideoDevice(console=True)`) y `CONFIG.TEXT_ENABLE` activo, el
texto 80x30 encima de lo anterior; el color 0 es transparente.
"""
from __future__ import annotations

import struct
from typing import Any

from PIL import Image, ImageDraw

from tools import console_render as cr

SCREEN_SIZE = (cr.WIDTH, cr.HEIGHT)
FRAME_BYTES = cr.FB_WIDTH * cr.FB_HEIGHT * 2

MODE_BLANK, MODE_PATTERN, MODE_SCANOUT = 0, 1, 2

# Barras de la prueba de PATTERN: blanco, amarillo, cian, verde, magenta,
# rojo, azul y negro. No pretende ser el patrón exacto del RTL.
PATTERN_BARS = ((255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
                (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0))

_RGB565_TABLE: list[bytes] | None = None


def _rgb565_table() -> list[bytes]:
    global _RGB565_TABLE
    if _RGB565_TABLE is None:
        _RGB565_TABLE = [bytes(cr._rgb565(value)) for value in range(65536)]
    return _RGB565_TABLE


def snapshot(machine) -> dict[str, Any]:
    """El estado de pantalla de un simulador, listo para componer o serializar."""
    video = machine.video
    if video is None:
        raise ValueError("el simulador no tiene vídeo (hace falta --video o --window)")
    framebuffer = None
    if video.video_mode == MODE_SCANOUT:
        base = video.fb_front
        if 0 <= base and base + FRAME_BYTES <= len(machine.memory):
            framebuffer = bytes(machine.memory[base:base + FRAME_BYTES])
    text = palette = None
    if video.console and video.config_active & video.CONFIG_TEXT_ENABLE:
        text = list(video.text_ram)
        palette = list(video.palette)
    return {"mode": video.video_mode, "fb": framebuffer, "text": text, "palette": palette}


class Compositor:
    """Compone pantallas con una fuente de 8x16. Guarda teselas entre frames."""

    def __init__(self, font: list[int]):
        self.font = font
        self._masks: dict[int, Image.Image] = {}
        self._tiles: dict[tuple, Image.Image] = {}
        self._pattern: Image.Image | None = None

    # ---- fondo -------------------------------------------------------------

    def _framebuffer(self, data: bytes) -> Image.Image:
        values = struct.unpack(f"<{FRAME_BYTES // 2}H", data)
        table = _rgb565_table()
        small = Image.frombytes("RGB", (cr.FB_WIDTH, cr.FB_HEIGHT),
                                b"".join([table[v] for v in values]))
        return small.resize(SCREEN_SIZE, Image.NEAREST)

    def _pattern_image(self) -> Image.Image:
        if self._pattern is None:
            image = Image.new("RGB", SCREEN_SIZE)
            draw = ImageDraw.Draw(image)
            width = cr.WIDTH // len(PATTERN_BARS)
            for index, color in enumerate(PATTERN_BARS):
                draw.rectangle([index * width, 0, (index + 1) * width - 1, cr.HEIGHT - 1],
                               fill=color)
            self._pattern = image
        return self._pattern

    # ---- texto -------------------------------------------------------------

    def _mask(self, glyph: int) -> Image.Image:
        mask = self._masks.get(glyph)
        if mask is None:
            word = self.font[glyph]
            pixels = bytearray(cr.CELL_W * cr.CELL_H)
            for y in range(cr.CELL_H):
                bits = (word >> (8 * y)) & 0xFF
                for x in range(cr.CELL_W):
                    if bits & (0x80 >> x):
                        pixels[y * cr.CELL_W + x] = 255
            mask = self._masks[glyph] = Image.frombytes("L", (cr.CELL_W, cr.CELL_H), bytes(pixels))
        return mask

    def _tile(self, cell: int, colors: list) -> Image.Image:
        fg, bg = colors[(cell >> 8) & 0xF], colors[(cell >> 12) & 0xF]
        key = (cell & 0xFF, fg, bg)
        tile = self._tiles.get(key)
        if tile is None:
            tile = Image.new("RGBA", (cr.CELL_W, cr.CELL_H),
                             (*bg, 255) if bg is not None else (0, 0, 0, 0))
            # Los píxeles del glifo llevan el color de primer plano; si ese
            # color es el 0 son transparentes y NO enseñan el fondo de la celda.
            tile.paste((*fg, 255) if fg is not None else (0, 0, 0, 0),
                       (0, 0), self._mask(cell & 0xFF))
            self._tiles[key] = tile
        return tile

    def _text_layer(self, text: list[int], palette: list[int]) -> Image.Image:
        colors = [None] + [((palette[i] >> 16) & 0xFF, (palette[i] >> 8) & 0xFF,
                            palette[i] & 0xFF) for i in range(1, 16)]
        layer = Image.new("RGBA", SCREEN_SIZE, (0, 0, 0, 0))
        for index, cell in enumerate(text[:cr.COLUMNS * cr.ROWS]):
            layer.paste(self._tile(cell, colors),
                        ((index % cr.COLUMNS) * cr.CELL_W, (index // cr.COLUMNS) * cr.CELL_H))
        return layer

    # ---- composición -------------------------------------------------------

    def compose(self, snap: dict[str, Any]) -> Image.Image:
        mode = snap["mode"]
        if mode == MODE_SCANOUT and snap.get("fb") is not None:
            image = self._framebuffer(snap["fb"])
        elif mode == MODE_PATTERN:
            image = self._pattern_image().copy()
        else:
            image = Image.new("RGB", SCREEN_SIZE)
        if snap.get("text") is not None:
            layer = self._text_layer(snap["text"], snap["palette"])
            image.paste(layer, (0, 0), layer)
        return image
