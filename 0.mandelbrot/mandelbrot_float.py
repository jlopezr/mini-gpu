# mandelbrot_float.py

import struct

WIDTH = 640
HEIGHT = 480
MAX_ITER = 256

X_MIN = -2.0
X_MAX = 1.0
Y_MIN = -1.125
Y_MAX = 1.125

OUTPUT_FILE = "mandelbrot.iter"


def mandelbrot(cx: float, cy: float, max_iter: int) -> int:
    zx = 0.0
    zy = 0.0

    for iteration in range(max_iter):
        zx2 = zx * zx
        zy2 = zy * zy

        if zx2 + zy2 >= 4.0:
            return iteration

        zy = 2.0 * zx * zy + cy
        zx = zx2 - zy2 + cx

    return max_iter


def pixel_to_complex(x: int, y: int) -> tuple[float, float]:
    cx = X_MIN + x * (X_MAX - X_MIN) / (WIDTH - 1)
    cy = Y_MAX - y * (Y_MAX - Y_MIN) / (HEIGHT - 1)

    return cx, cy


def main():
    with open(OUTPUT_FILE, "wb") as f:
        # Cabecera
        f.write(b"ITER")
        f.write(struct.pack("<III", WIDTH, HEIGHT, MAX_ITER))

        # Datos
        for y in range(HEIGHT):
            for x in range(WIDTH):
                cx, cy = pixel_to_complex(x, y)
                iterations = mandelbrot(cx, cy, MAX_ITER)

                f.write(struct.pack("<H", iterations))

    print(f"Generado {OUTPUT_FILE}")
    print(f"{WIDTH}x{HEIGHT}, max_iter={MAX_ITER}")


if __name__ == "__main__":
    main()