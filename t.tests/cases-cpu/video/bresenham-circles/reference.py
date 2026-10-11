#!/usr/bin/env python3
"""Modelo independiente del primer frame de bresenham_circles.asm."""
from pathlib import Path

WIDTH, HEIGHT = 320, 240
CX, CY = 160, 120


def circle(radius):
    x, y, error = radius, 0, 0
    while x >= y:
        yield from ((CX+x, CY+y), (CX-x, CY+y),
                    (CX-x, CY-y), (CX+x, CY-y),
                    (CX+y, CY+x), (CX-y, CY+x),
                    (CX-y, CY-x), (CX+y, CY-x))
        y += 1
        error += 2 * y + 1
        if 2 * (error - x) + 1 > 0:
            x -= 1
            error += 1 - 2 * x


pixels = [0] * (WIDTH * HEIGHT)
for number in range(6):
    color = ((31 - 5 * number) << 11) | (5 * number + 1)
    for x, y in circle(4 + 18 * number):
        pixels[y * WIDTH + x] = color

data = b"".join(value.to_bytes(2, "little") for value in pixels)
target = Path(__file__).parent / "expected" / "frame.bin"
target.parent.mkdir(exist_ok=True)
target.write_bytes(data)
print(f"{len(data)} bytes -> {target}")
