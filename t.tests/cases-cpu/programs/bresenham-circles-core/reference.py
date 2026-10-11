#!/usr/bin/env python3
"""Genera por separado las emisiones del algoritmo del punto medio."""
from pathlib import Path

RADII = (0, 1, 2, 3, 4, 7, 18)
CX = CY = 32


def circle(radius):
    emitted = []
    x, y, error = radius, 0, 0
    while x >= y:
        emitted.extend(((CX+x, CY+y), (CX-x, CY+y),
                        (CX-x, CY-y), (CX+x, CY-y),
                        (CX+y, CY+x), (CX-y, CY+x),
                        (CX-y, CY-x), (CX+y, CY-x)))
        y += 1
        error += 2 * y + 1
        if 2 * (error - x) + 1 > 0:
            x -= 1
            error += 1 - 2 * x
    return emitted


words = []
for radius in RADII:
    points = circle(radius)
    slot = [len(points)] + [(y << 16) | x for x, y in points]
    words.extend(slot + [0] * (128 - len(slot)))

target = Path(__file__).parent / "expected.hex"
target.write_text("".join(f"{word:08x}\n" for word in words), encoding="ascii")
print(f"{len(words)} palabras -> {target}")
