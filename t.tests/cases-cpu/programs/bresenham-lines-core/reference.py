#!/usr/bin/env python3
"""Genera la secuencia esperada con una formulacion independiente."""
from pathlib import Path

CASES = [
    (5, 5, 5, 5), (1, 4, 13, 4), (13, 4, 1, 4),
    (7, 1, 7, 13), (7, 13, 7, 1),
    (8, 8, 14, 10), (8, 8, 10, 14), (8, 8, 6, 14),
    (8, 8, 2, 10), (8, 8, 2, 6), (8, 8, 6, 2),
    (8, 8, 10, 2), (8, 8, 14, 6),
]


def line(x0, y0, x1, y1):
    points = []
    dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
    dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        points.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return points
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


words = []
for case in CASES:
    points = line(*case)
    slot = [len(points)] + [(y << 16) | x for x, y in points]
    words.extend(slot + [0] * (32 - len(slot)))

target = Path(__file__).parent / "expected.hex"
target.write_text("".join(f"{word:08x}\n" for word in words), encoding="ascii")
print(f"{len(words)} palabras -> {target}")
