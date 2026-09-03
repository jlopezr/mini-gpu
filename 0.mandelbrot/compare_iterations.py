# compare_iterations.py

import struct

FILE_A = "mandelbrot.iter"
FILE_B = "mandelbrot_fixed.iter"


def read_iterations(filename):
    with open(filename, "rb") as f:
        magic = f.read(4)

        if magic != b"ITER":
            raise ValueError(f"{filename}: formato ITER inválido")

        width, height, max_iter = struct.unpack("<III", f.read(12))

        values = []

        for _ in range(width * height):
            data = f.read(2)

            if len(data) != 2:
                raise ValueError(f"{filename}: archivo truncado")

            value, = struct.unpack("<H", data)
            values.append(value)

    return width, height, max_iter, values


def main():
    width_a, height_a, max_iter_a, values_a = read_iterations(FILE_A)
    width_b, height_b, max_iter_b, values_b = read_iterations(FILE_B)

    if width_a != width_b or height_a != height_b:
        raise ValueError(
            "Las imágenes tienen dimensiones diferentes: "
            f"{width_a}x{height_a} vs {width_b}x{height_b}"
        )

    if max_iter_a != max_iter_b:
        raise ValueError(
            "MAX_ITER diferente: "
            f"{max_iter_a} vs {max_iter_b}"
        )

    total_pixels = width_a * height_a

    different_pixels = 0
    total_difference = 0
    max_difference = 0
    max_difference_position = None

    difference_histogram = {}

    for index, (a, b) in enumerate(zip(values_a, values_b)):
        difference = abs(a - b)

        if difference == 0:
            continue

        different_pixels += 1
        total_difference += difference

        difference_histogram[difference] = (
            difference_histogram.get(difference, 0) + 1
        )

        if difference > max_difference:
            max_difference = difference

            x = index % width_a
            y = index // width_a

            max_difference_position = (x, y, a, b)

    equal_pixels = total_pixels - different_pixels

    print("Comparación ITER")
    print("================")
    print(f"A: {FILE_A}")
    print(f"B: {FILE_B}")
    print()

    print(f"Resolución:          {width_a}x{height_a}")
    print(f"Total píxeles:       {total_pixels}")
    print(f"Píxeles iguales:     {equal_pixels}")
    print(f"Píxeles diferentes:  {different_pixels}")

    percentage = different_pixels * 100.0 / total_pixels

    print(f"Diferentes (%):      {percentage:.6f}%")

    if different_pixels == 0:
        print()
        print("Los dos archivos son idénticos píxel a píxel.")
        return

    average_difference = total_difference / different_pixels

    print()
    print(f"Diferencia media:    {average_difference:.3f} iteraciones")
    print(f"Diferencia máxima:   {max_difference} iteraciones")

    if max_difference_position is not None:
        x, y, a, b = max_difference_position

        print()
        print("Máxima diferencia:")
        print(f"  píxel:             ({x}, {y})")
        print(f"  float:             {a}")
        print(f"  fixed:             {b}")

    print()
    print("Histograma de diferencias")
    print("-------------------------")

    for difference in sorted(difference_histogram):
        count = difference_histogram[difference]

        print(
            f"{difference:4d} iteraciones: "
            f"{count:8d} píxeles"
        )


if __name__ == "__main__":
    main()