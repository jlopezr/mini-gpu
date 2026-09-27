#!/usr/bin/env python3
"""Genera las tablas v3 y v4 del cubo solido animado para MiniGPU."""

import math
from pathlib import Path

ONE = 1 << 16
VERTICES = [
    (-ONE, -ONE, -ONE), (ONE, -ONE, -ONE),
    (-ONE, ONE, -ONE), (ONE, ONE, -ONE),
    (-ONE, -ONE, ONE), (ONE, -ONE, ONE),
    (-ONE, ONE, ONE), (ONE, ONE, ONE),
]
FACES = [
    (0, 1, 3, 2, 0xF800), (4, 6, 7, 5, 0x001F),
    (0, 4, 5, 1, 0xFFE0), (2, 3, 7, 6, 0x07E0),
    (0, 2, 6, 4, 0x07FF), (1, 5, 7, 3, 0xF81F),
]
SINE = [int(round(math.sin(2 * math.pi * i / 256) * ONE)) for i in range(256)]


def mulfx(a: int, b: int) -> int:
    return (a * b) >> 16


def div0(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def project(iteration: int) -> list[tuple[int, int]]:
    a, b = iteration & 255, (3 * iteration) & 255
    sa, ca = SINE[a], SINE[(a + 64) & 255]
    sb, cb = SINE[b], SINE[(b + 64) & 255]
    out = []
    for x, y, z in VERTICES:
        y1 = mulfx(y, ca) - mulfx(z, sa)
        z1 = mulfx(y, sa) + mulfx(z, ca)
        x2 = mulfx(x, cb) + mulfx(z1, sb)
        z2 = mulfx(z1, cb) - mulfx(x, sb)
        xi, yi, zi = x2 >> 8, y1 >> 8, (z2 + 3 * ONE) >> 8
        out.append((160 + div0(xi * 140, zi), 120 + div0(yi * 140, zi)))
    return out


def descriptor(p0, p1, p2, color):
    values = []
    for (x0, y0), (x1, y1) in ((p0, p1), (p1, p2), (p2, p0)):
        dx, dy = x1 - x0, y1 - y0
        values += [-dy, dx, dy * x0 - dx * y0]
    values.append(color | (color << 16))
    return values


def frames():
    result = []
    for frame in range(64):
        points = project(frame * 4)
        triangles = []
        for i0, i1, i2, i3, color in FACES:
            p0, p1, p2, p3 = points[i0], points[i1], points[i2], points[i3]
            area = ((p1[0] - p0[0]) * (p2[1] - p0[1])
                    - (p1[1] - p0[1]) * (p2[0] - p0[0]))
            if area > 0:
                triangles.append((descriptor(p0, p1, p2, color), (p0, p1, p2)))
                triangles.append((descriptor(p0, p2, p3, color), (p0, p2, p3)))
        while len(triangles) < 6:
            triangles.append(([0, 0, -1, 0, 0, -1, 0, 0, -1, 0], None))
        assert len(triangles) == 6
        result.append(triangles)
    return result


def main() -> None:
    all_frames = frames()
    lines = [
        "; Generado por make_cube_solid_frames.py; no editar a mano.",
        "; 64 frames, seis descriptores de 10 palabras por frame.",
        "cube_frames:",
    ]
    for frame, triangles in enumerate(all_frames):
        lines.append(f"; frame {frame}: iteracion {frame * 4}")
        for triangle, _points in triangles:
            lines.append("    .word " + ", ".join(str(v) for v in triangle))
    lines.append("cube_frames_end:")
    Path(__file__).with_name("cube_solid_frames_v3.inc").write_text(
        "\n".join(lines) + "\n", encoding="ascii")

    # v4 añade caja por triangulo. X se expande a grupos de ocho palabras para
    # que las ocho lanes de un warp recorran siempre bloques completos.
    lines = [
        "; Generado por make_cube_solid_frames.py; no editar a mano.",
        "; 64 frames, seis descriptores de 14 palabras por frame.",
        "cube_frames:",
    ]
    for frame, triangles in enumerate(all_frames):
        lines.append(f"; frame {frame}: iteracion {frame * 4}")
        for triangle, points in triangles:
            if points is None:
                box = [0, 7, 1, 0]       # maxy < miny: descriptor inactivo
            else:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                min_word = max(0, (min(xs) // 2) & ~7)
                max_word = min(159, (max(xs) // 2) | 7)
                box = [min_word, max_word, max(0, min(ys)), min(239, max(ys))]
            lines.append("    .word " + ", ".join(str(v) for v in triangle + box))
    lines.append("cube_frames_end:")
    Path(__file__).with_name("cube_solid_frames_v4.inc").write_text(
        "\n".join(lines) + "\n", encoding="ascii")

    # v5 calcula la geometria en la GPU. Solo conserva una tabla trigonometrica
    # Q2.14 (1 KiB), frente a los 21 KiB de descriptores precalculados de v4.
    sine_q14 = [int(round(math.sin(2 * math.pi * i / 256) * (1 << 14)))
                for i in range(256)]
    lines = [
        "; Generado por make_cube_solid_frames.py; no editar a mano.",
        "; sin(2*pi*i/256) en Q2.14.",
        "cube_sine_q14:",
    ]
    for i in range(0, 256, 8):
        lines.append("    .word " + ", ".join(str(v) for v in sine_q14[i:i + 8]))
    Path(__file__).with_name("cube_sine_q14.inc").write_text(
        "\n".join(lines) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
