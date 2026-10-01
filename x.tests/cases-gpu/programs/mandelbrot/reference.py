"""Modelo de referencia: genera expected.bin desde la referencia escalar Q16.16.

Es independiente del ensamblador y de la GPU: el número de iteraciones de cada
píxel sale de `0.mandelbrot/mandelbrot_fixed.py`, una palabra de 32 bits por
píxel en orden de exploración. `run.py` lo reutiliza con `--reference-only`, y
`run_tests.py` lo ejecuta solo cuando falta `expected.bin`.
"""

import runpy
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]

WIDTH, HEIGHT, MAX_ITER = 320, 240, 256


def generate_reference() -> None:
    reference = runpy.run_path(str(ROOT / "0.mandelbrot/mandelbrot_fixed.py"))
    values = [reference["mandelbrot"](*reference["pixel_to_complex"](x, y), MAX_ITER)
              for y in range(HEIGHT) for x in range(WIDTH)]
    (HERE / "expected.bin").write_bytes(struct.pack(f"<{len(values)}I", *values))
    print("Generado expected.bin desde la referencia escalar", flush=True)


if __name__ == "__main__":
    generate_reference()
    sys.exit(0)
