"""Patrones de diagnóstico para framebuffers RGB565 de 320x240."""

from __future__ import annotations

import struct

WIDTH = 320
HEIGHT = 240


def rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def bars(x: int, y: int) -> int:
    del y
    palette = [
        (255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
        (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0),
    ]
    return rgb565(*palette[(x * len(palette)) // WIDTH])


def diagonal(x: int, y: int) -> int:
    if (x * HEIGHT) // WIDTH == y:
        return 0xFFFF
    return rgb565(x * 255 // (WIDTH - 1), y * 255 // (HEIGHT - 1), 0)


def checker(x: int, y: int) -> int:
    return 0xFFFF if ((x // 16) + (y // 16)) % 2 else 0x0000


def gradient(x: int, y: int) -> int:
    return rgb565(x * 255 // (WIDTH - 1), y * 255 // (HEIGHT - 1), 0)


def frame(x: int, y: int) -> int:
    if x in (0, WIDTH - 1) or y in (0, HEIGHT - 1):
        return rgb565(255, 255, 255)
    if x == WIDTH // 2 or y == HEIGHT // 2:
        return rgb565(255, 0, 0)
    return 0x0000


PATTERNS = {
    "bars": bars,
    "diagonal": diagonal,
    "checker": checker,
    "gradient": gradient,
    "frame": frame,
}


def render(pattern: str) -> bytes:
    generate = PATTERNS[pattern]
    pixels = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixels += struct.pack("<H", generate(x, y) & 0xFFFF)
    return bytes(pixels)
