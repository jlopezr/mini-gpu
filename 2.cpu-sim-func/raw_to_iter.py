#!/usr/bin/env python3
"""
Convierte un framebuffer raw de MiniCPU a un fichero .iter.

Entrada:

- un uint32 little-endian por píxel
- contenido exacto de la memoria escrita por STORE

Salida:

- cabecera ``ITER`` con anchura, altura y máximo de iteraciones
- un uint16 little-endian por píxel

El conversor comprueba el tamaño del framebuffer y rechaza cualquier valor
que no quepa en 16 bits, evitando truncamientos silenciosos.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


def convert_raw_to_iter(
    raw_data: bytes,
    width: int,
    height: int,
    max_iter: int = 256,
) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError("width y height deben ser positivos")
    if not 0 < max_iter <= 0xFFFFFFFF:
        raise ValueError("max_iter debe estar entre 1 y 2^32 - 1")

    pixel_count = width * height
    expected_size = pixel_count * 4

    if len(raw_data) != expected_size:
        raise ValueError(
            f"tamaño raw incorrecto: esperados {expected_size} bytes "
            f"para {width}x{height}, recibidos {len(raw_data)}"
        )

    header = struct.pack("<4sIII", b"ITER", width, height, max_iter)
    iter_data = bytearray(len(header) + pixel_count * 2)
    iter_data[: len(header)] = header

    for index in range(pixel_count):
        value = struct.unpack_from("<I", raw_data, index * 4)[0]

        if value > 0xFFFF:
            x = index % width
            y = index // width
            raise ValueError(
                f"el píxel ({x}, {y}) contiene {value}, "
                f"que no cabe en uint16"
            )

        struct.pack_into("<H", iter_data, len(header) + index * 2, value)

    return bytes(iter_data)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convierte framebuffer raw uint32 LE a .iter uint16 LE"
    )
    parser.add_argument("raw", type=Path, help="framebuffer raw de entrada")
    parser.add_argument("iter", type=Path, help="fichero .iter de salida")
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--max-iter", type=int, default=256)
    args = parser.parse_args()

    raw_data = args.raw.read_bytes()
    iter_data = convert_raw_to_iter(
        raw_data,
        args.width,
        args.height,
        args.max_iter,
    )
    args.iter.write_bytes(iter_data)

    print(
        f"Convertidos {args.width * args.height} píxeles: "
        f"{len(raw_data)} bytes raw -> {len(iter_data)} bytes .iter"
    )


if __name__ == "__main__":
    main()
