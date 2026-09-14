"""Genera expected.bin desde la referencia escalar Q16.16.

El framebuffer empaquetado es un byte por pixel, saturado a 255, en el mismo
orden de exploracion que la version de una palabra por pixel. Como el kernel
mete cuatro pixeles consecutivos en una palabra little-endian, la palabra que
escribe la GPU y la secuencia de bytes de este fichero son la misma cosa.
"""

import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

WIDTH, HEIGHT, MAX_ITER = 320, 240, 256


def main() -> int:
    reference = runpy.run_path(str(ROOT / "0.mandelbrot/mandelbrot_fixed.py"))
    mandelbrot = reference["mandelbrot"]
    pixel_to_complex = reference["pixel_to_complex"]

    # Saturar a 255: el kernel hace lo mismo sin ramificar con iter - (iter>>8),
    # y solo afecta a los puntos del interior, que alcanzan MAX_ITER = 256.
    values = bytes(
        min(mandelbrot(*pixel_to_complex(x, y), MAX_ITER), 255)
        for y in range(HEIGHT)
        for x in range(WIDTH)
    )

    (HERE / "expected.bin").write_bytes(values)
    saturated = sum(1 for value in values if value == 255)
    print(f"expected.bin: {len(values)} bytes, {saturated} pixeles saturados a 255")
    return 0


if __name__ == "__main__":
    sys.exit(main())
