#!/usr/bin/env python3
"""Modelo de referencia de `warp_lane_bands.asm`: genera `expected.bin`.

Independiente del programa: sale de lo que el programa DICE que pinta, no de
ejecutarlo. Cada warp una banda de 30 filas con su color base; dentro de ella,
la lane `l` pinta las palabras de indice `l, l+8, l+16...` con el color base
escalado por `(l+1)/8` canal a canal. Cada palabra de 32 bits son dos pixeles
iguales.

    python reference.py            # reescribe expected.bin (153 600 bytes)
"""
from pathlib import Path

WIDTH, HEIGHT = 320, 240
BASES = (0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF, 0xF81F, 0xFC00, 0xFFFF)
ROWS_PER_WARP = 30
LANES = 8


def scaled(color: int, lane: int) -> int:
    factor = lane + 1
    red = ((color >> 11) & 0x1F) * factor >> 3
    green = ((color >> 5) & 0x3F) * factor >> 3
    blue = (color & 0x1F) * factor >> 3
    return (red << 11) | (green << 5) | blue


def frame() -> bytes:
    image = bytearray()
    for warp in range(len(BASES)):
        words = ROWS_PER_WARP * WIDTH // 2
        for index in range(words):
            pixel = scaled(BASES[warp], index % LANES)
            image += pixel.to_bytes(2, "little") * 2
    assert len(image) == WIDTH * HEIGHT * 2
    return bytes(image)


if __name__ == "__main__":
    destino = Path(__file__).with_name("expected.bin")
    destino.write_bytes(frame())
    print(f"{destino} ({destino.stat().st_size} bytes)")
