# view_iterations.py

import struct

from PIL import Image

INPUT_FILE = "mandelbrot.iter"
OUTPUT_FILE = "mandelbrot.png"


def read_iterations(filename):
    with open(filename, "rb") as f:
        magic = f.read(4)

        if magic != b"ITER":
            raise ValueError("No es un archivo ITER válido")

        width, height, max_iter = struct.unpack("<III", f.read(12))

        values = []

        for _ in range(width * height):
            value, = struct.unpack("<H", f.read(2))
            values.append(value)

    return width, height, max_iter, values


def iteration_to_rgb(iteration, max_iter):
    if iteration >= max_iter:
        return 0, 0, 0

    # Visualización inicial muy sencilla.
    value = int(255 * iteration / max_iter)

    return value, value, value


def main():
    width, height, max_iter, values = read_iterations(INPUT_FILE)

    image = Image.new("RGB", (width, height))
    pixels = image.load()

    for y in range(height):
        for x in range(width):
            iteration = values[y * width + x]

            pixels[x, y] = iteration_to_rgb(
                iteration,
                max_iter,
            )

    image.save(OUTPUT_FILE)

    print(f"Generado {OUTPUT_FILE}")


if __name__ == "__main__":
    main()