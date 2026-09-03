# mandelbrot_fixed.py

import struct

WIDTH = 640
HEIGHT = 480
MAX_ITER = 256

FRAC_BITS = 16
SCALE = 1 << FRAC_BITS

X_MIN = int(-2.0 * SCALE)
X_MAX = int( 1.0 * SCALE)

Y_MIN = int(-1.125 * SCALE)
Y_MAX = int( 1.125 * SCALE)

ESCAPE_RADIUS_SQUARED = 4 * SCALE

OUTPUT_FILE = "mandelbrot_fixed.iter"


def to_int32(value: int) -> int:
    """
    Fuerza un valor al comportamiento de un entero signed de 32 bits.
    """
    value &= 0xFFFFFFFF

    if value & 0x80000000:
        value -= 0x100000000

    return value


def fixed_mul(a: int, b: int) -> int:
    """
    Multiplica dos Q16.16.

    a y b son enteros signed de 32 bits.
    El producto intermedio es conceptualmente signed de 64 bits.

    Resultado:
        (a * b) >> 16
    """
    result = (a * b) >> FRAC_BITS
    return to_int32(result)


def fixed_add(a: int, b: int) -> int:
    return to_int32(a + b)


def fixed_sub(a: int, b: int) -> int:
    return to_int32(a - b)


def mandelbrot(cx: int, cy: int, max_iter: int) -> int:
    zx = 0
    zy = 0

    for iteration in range(max_iter):
        zx2 = fixed_mul(zx, zx)
        zy2 = fixed_mul(zy, zy)

        magnitude_squared = fixed_add(zx2, zy2)

        if magnitude_squared >= ESCAPE_RADIUS_SQUARED:
            return iteration

        zx_zy = fixed_mul(zx, zy)

        # zy = 2*zx*zy + cy
        new_zy = fixed_add(
            fixed_add(zx_zy, zx_zy),
            cy,
        )

        # zx = zx² - zy² + cx
        new_zx = fixed_add(
            fixed_sub(zx2, zy2),
            cx,
        )

        zx = new_zx
        zy = new_zy

    return max_iter


def pixel_to_complex(x: int, y: int) -> tuple[int, int]:
    """
    Convierte píxel -> coordenada compleja directamente en Q16.16.

    No usa float.
    """

    cx = X_MIN + (
        x * (X_MAX - X_MIN)
    ) // (WIDTH - 1)

    cy = Y_MAX - (
        y * (Y_MAX - Y_MIN)
    ) // (HEIGHT - 1)

    return to_int32(cx), to_int32(cy)


def main():
    with open(OUTPUT_FILE, "wb") as f:
        # Mismo formato ITER que usamos con la versión float.
        f.write(b"ITER")
        f.write(struct.pack("<III", WIDTH, HEIGHT, MAX_ITER))

        for y in range(HEIGHT):
            for x in range(WIDTH):
                cx, cy = pixel_to_complex(x, y)

                iterations = mandelbrot(
                    cx,
                    cy,
                    MAX_ITER,
                )

                f.write(struct.pack("<H", iterations))

    print(f"Generado {OUTPUT_FILE}")
    print(
        f"{WIDTH}x{HEIGHT}, "
        f"max_iter={MAX_ITER}, "
        f"Q{32 - FRAC_BITS}.{FRAC_BITS}"
    )


if __name__ == "__main__":
    main()