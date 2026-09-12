"""Genera imágenes RGB565 de 320x240 para cargar en el framebuffer.

El framebuffer vive en `0x01000000`, es lineal y sin relleno: 320 píxeles de
16 bits por línea, 240 líneas, 153 600 bytes en total. Las palabras se guardan
en little-endian, que es como las lee el monitor y como las entrega la SDRAM.

Uso típico:

    python make_framebuffer.py bars fb.bin
    python monitor.py write-block 0x01000000 fb.bin --port COM3

Los patrones están pensados para diagnosticar, no para lucir:

  bars        barras de color verticales. Un byte intercambiado dentro del
              píxel salta a la vista: los colores salen equivocados pero las
              barras siguen rectas.
  diagonal    diagonal blanca sobre degradado. Delata cualquier error de pitch
              o de línea: si la base de línea está mal, la diagonal se escalona.
  checker     tablero de 16x16. Revela desplazamientos de medio píxel y
              problemas de escalado 2x.
  gradient    degradado rojo horizontal y verde vertical, sin bordes. Sirve
              para ver bandas y saltos de color.
  frame       marco de un píxel y cruz central. Comprueba que se ve la imagen
              entera y que el monitor no recorta bordes.
"""

import argparse
import struct
import sys

WIDTH = 320
HEIGHT = 240
FB_BASE = 0x01000000


def rgb565(r, g, b):
    """Empaqueta tres componentes de 8 bits en un pixel RGB565."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def bars(x, y):
    del y
    palette = [
        (255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
        (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0),
    ]
    return rgb565(*palette[(x * len(palette)) // WIDTH])


def diagonal(x, y):
    if (x * HEIGHT) // WIDTH == y:
        return 0xFFFF
    return rgb565(x * 255 // (WIDTH - 1), y * 255 // (HEIGHT - 1), 0)


def checker(x, y):
    return 0xFFFF if ((x // 16) + (y // 16)) % 2 else 0x0000


def gradient(x, y):
    return rgb565(x * 255 // (WIDTH - 1), y * 255 // (HEIGHT - 1), 0)


def frame(x, y):
    on_border = x in (0, WIDTH - 1) or y in (0, HEIGHT - 1)
    on_cross = x == WIDTH // 2 or y == HEIGHT // 2
    if on_border:
        return rgb565(255, 255, 255)
    if on_cross:
        return rgb565(255, 0, 0)
    return 0x0000


PATTERNS = {
    "bars": bars,
    "diagonal": diagonal,
    "checker": checker,
    "gradient": gradient,
    "frame": frame,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pattern", choices=sorted(PATTERNS))
    parser.add_argument("output")
    arguments = parser.parse_args(argv)

    generate = PATTERNS[arguments.pattern]
    pixels = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixels += struct.pack("<H", generate(x, y) & 0xFFFF)

    with open(arguments.output, "wb") as handle:
        handle.write(pixels)

    print(f"{arguments.output}: {len(pixels)} bytes "
          f"({WIDTH}x{HEIGHT} RGB565), cargar en 0x{FB_BASE:08x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
