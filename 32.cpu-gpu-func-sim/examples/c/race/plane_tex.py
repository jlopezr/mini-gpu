#!/usr/bin/env python3
"""Convierte plane/logos.png (Autobots a la izquierda, Decepticons a la derecha) en las dos texturas de plane.c.

    python examples/c/race/plane_tex.py [-o plane_tex.bin] [--preview vista.png]

Cada textura es de 128 x 128 palabras: la delantera (Autobots) y la trasera (Decepticons), una detras
de otra (128 KiB). Una palabra es un texel con su alfa:

    bits 0-4 azul, 5-10 alfa (0..32), 11-15 rojo, 21-26 verde      (el resto, a cero)

Es el RGB565 "abierto" (rojo y azul a un lado, verde al otro, con los huecos libres) de la mezcla de
plane_body.h: `texel & PLANE_MASK` ya esta abierto y el alfa cae en el hueco entre azul y rojo.

El alfa sale del fondo negro: lo que es casi negro y se alcanza desde el borde de la imagen es
transparente; el negro interior de los logos (el triangulo de la frente de los Autobots) es opaco. El
borde se suaviza al reducir la mascara. Hay una linea blanca en diagonal entre los dos logos: se pinta de
negro antes de buscar el fondo.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "plane" / "logos.png"
SIZE = 128                      # texeles por lado
MARGIN = 4                      # transparentes en cada borde, para que el borde de la textura nunca pinte
DARK = 30                       # canal maximo por debajo del cual un pixel es "fondo"
FRAME = 8                       # el borde de la imagen trae un filete claro: se pinta de negro
LINE_X0, LINE_SLOPE, LINE_HALF = 760.5, -0.0606, 4.5     # la linea divisoria: x = X0 + SLOPE * y


def divider(y: int) -> float:
    return LINE_X0 + LINE_SLOPE * y


def half(image: Image.Image, left: bool) -> Image.Image:
    """La mitad izquierda o derecha, con el otro lado y la linea en negro."""
    out = image.copy()
    px = out.load()
    width, height = out.size
    for y in range(height):
        cut = divider(y)
        for x in range(width):
            frame = min(x, y, width - 1 - x, height - 1 - y) < FRAME
            if frame or ((x > cut - LINE_HALF) if left else (x < cut + LINE_HALF)):
                px[x, y] = (0, 0, 0)
    return out


def background_mask(image: Image.Image) -> Image.Image:
    """'L' de 0/255: 255 donde hay logo, 0 en el fondo alcanzable desde el borde."""
    channels = [c.point(lambda v: 255 if v < DARK else 0) for c in image.split()]
    dark = ImageChops.multiply(ImageChops.multiply(channels[0], channels[1]), channels[2])
    dark = dark.filter(ImageFilter.MinFilter(3))        # un pixel claro suelto no corta el fondo
    dark = dark.point(lambda v: 1 if v else 0)
    flood = dark.copy()
    width, height = flood.size
    for seed in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]:
        if flood.getpixel(seed) == 1:
            ImageDraw.floodfill(flood, seed, 2)
    return flood.point(lambda v: 0 if v == 2 else 255)  # fondo (2) -> 0; todo lo demas -> logo


def texture(image: Image.Image, left: bool) -> list[int]:
    side = half(image, left)
    mask = background_mask(side)
    mask = mask.filter(ImageFilter.MaxFilter(3))        # recupera lo que MinFilter se comio del contorno
    box = mask.getbbox()
    cropped = side.crop(box)
    cropped_mask = mask.crop(box)
    inner = SIZE - 2 * MARGIN
    scale = inner / max(cropped.size)
    new = (max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale)))
    rgb = cropped.resize(new, Image.LANCZOS)
    alpha = cropped_mask.resize(new, Image.LANCZOS)
    canvas = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    canvas_alpha = Image.new("L", (SIZE, SIZE), 0)
    where = ((SIZE - new[0]) // 2, (SIZE - new[1]) // 2)
    canvas.paste(rgb, where)
    canvas_alpha.paste(alpha, where)
    rgb_bytes, alpha_bytes = canvas.tobytes(), canvas_alpha.tobytes()
    return [pack(rgb_bytes[3 * i], rgb_bytes[3 * i + 1], rgb_bytes[3 * i + 2],
                 round(alpha_bytes[i] * 32 / 255)) for i in range(SIZE * SIZE)]


def pack(r: int, g: int, b: int, alpha: int) -> int:
    return ((g >> 2) << 21) | ((r >> 3) << 11) | (alpha << 5) | (b >> 3)


def unpack(word: int) -> tuple[int, int, int, int]:
    """(r, g, b de 8 bits, alfa 0..32), la inversa de `pack` hasta el redondeo de 565."""
    r, g, b = (word >> 11) & 31, (word >> 21) & 63, word & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2, (word >> 5) & 63)


def gradient(rows: int = 104) -> list[tuple[int, int, int]]:
    """El fondo de plane.c: vertical, de azul oscuro arriba a naranja apagado abajo."""
    top, bottom = (24, 40, 96), (200, 120, 48)
    return [tuple(round(t + (b - t) * y / (rows - 1)) for t, b in zip(top, bottom)) for y in range(rows)]


def preview(textures: list[list[int]], path: Path) -> None:
    sheet = Image.new("RGB", (SIZE * 2 * 3, SIZE * 3))
    for index, words in enumerate(textures):
        tile = Image.new("RGB", (SIZE, SIZE))
        bg = gradient(SIZE)
        data = []
        for i, word in enumerate(words):
            r, g, b, a = unpack(word)
            br, bgn, bb = bg[i // SIZE]
            data.append((br + (r - br) * a // 32, bgn + (g - bgn) * a // 32, bb + (b - bb) * a // 32))
        tile.putdata(data)
        sheet.paste(tile.resize((SIZE * 3, SIZE * 3), Image.NEAREST), (index * SIZE * 3, 0))
    sheet.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", type=Path, default=HERE / "_plane_tex.bin")
    parser.add_argument("--preview", type=Path, help="un PNG con las dos texturas sobre el degradado")
    parser.add_argument("--source", type=Path, default=SOURCE)
    args = parser.parse_args()
    image = Image.open(args.source).convert("RGB")
    textures = [texture(image, True), texture(image, False)]
    args.output.write_bytes(b"".join(struct.pack(f"<{len(t)}I", *t) for t in textures))
    if args.preview:
        preview(textures, args.preview)
    print(f"{args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
