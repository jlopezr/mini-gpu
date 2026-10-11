#!/usr/bin/env python3
"""Modelo independiente del primer frame de bresenham_lines.asm."""
from pathlib import Path

WIDTH, HEIGHT = 320, 240


def edge(position):
    if position < 320:
        return position, 0
    if position < 559:
        return 319, position - 319
    if position < 878:
        return 877 - position, 239
    return 0, 1116 - position


def line(x0, y0, x1, y1):
    dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
    dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        yield x0, y0
        if (x0, y0) == (x1, y1):
            return
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


pixels = [0] * (WIDTH * HEIGHT)
position = 0
for number in range(36):
    color = ((number // 2) << 11) | ((63 - number) << 5) | 15
    for x, y in line(160, 120, *edge(position)):
        pixels[y * WIDTH + x] = color
    position = (position + 31) % 1116

data = b"".join(value.to_bytes(2, "little") for value in pixels)
target = Path(__file__).parent / "expected" / "frame.bin"
target.parent.mkdir(exist_ok=True)
target.write_bytes(data)
print(f"{len(data)} bytes -> {target}")
