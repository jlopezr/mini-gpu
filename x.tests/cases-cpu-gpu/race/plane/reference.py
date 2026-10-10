#!/usr/bin/env python3
"""Genera el cuerpo visible esperado del tercer frame de plane_test.c."""
from __future__ import annotations

import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASK = 0x07E0F81F
SIN = [0, 13, 25, 37, 49, 60, 71, 81, 91, 99, 106, 113, 118, 122, 126, 127,
       128, 127, 126, 122, 118, 113, 106, 99, 91, 81, 71, 60, 49, 37, 25, 13,
       0, -13, -25, -37, -49, -60, -71, -81, -91, -99, -106, -113, -118,
       -122, -126, -127, -128, -127, -126, -122, -118, -113, -106, -99,
       -91, -81, -71, -60, -49, -37, -25, -13]


def background() -> list[int]:
    rows = []
    for y in range(104):
        r = 24 + 176 * y // 103
        g = 40 + 80 * y // 103
        b = 96 - 48 * y // 103
        color = (r >> 3) << 11 | (g >> 2) << 5 | b >> 3
        rows.append((color | color << 16) & MASK)
    return rows


def image(frame: int, textures: tuple[int, ...]) -> bytes:
    c = SIN[((frame & 63) + 16) & 63]
    texture = textures[16384 if c < 0 else 0:][:16384]
    u00, ux = 0x40000000, 0
    if abs(c) >= 8:
        ux = 170 * 128 // abs(c)
        u00 = 64 * 128 - 80 * ux
    v00 = 64 * 128 - 52 * 170
    out = bytearray()
    for y, bgx in enumerate(background()):
        bg16 = (bgx | bgx >> 16) & 0xFFFF
        row = []
        v = v00 + y * 170
        for x in range(160):
            u = u00 + x * ux
            if 0 <= v < 16384 and 0 <= u < 16384:
                texel = texture[(v & 0x3F80) + (u >> 7)]
                alpha = texel >> 5 & 63
                opened = (((((texel & MASK) - bgx) & 0xFFFFFFFF) * alpha
                           & 0xFFFFFFFF) >> 5) + bgx & MASK
                pixel = (opened | opened >> 16) & 0xFFFF
            else:
                pixel = bg16
            row.append(pixel * 65537)
        out += struct.pack("<160I", *row) * 2
    return bytes(out)


def main() -> int:
    texture_path = HERE.parents[3] / "_build" / "c" / "plane_tex.bin"
    words = struct.unpack(f"<{texture_path.stat().st_size // 4}I", texture_path.read_bytes())
    output = HERE / "_build" / "expected.bin"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image(2, words))
    print(f"{output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
