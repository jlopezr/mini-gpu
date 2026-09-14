#!/usr/bin/env python3
"""Convierte un framebuffer RGB565 en una imagen mirable.

Come lo que producen los tres sitios donde aparece un framebuffer en este
repositorio, sin tener que convertir entre ellos:

  - `.bin`  RGB565 crudo, little-endian. Es lo que vuelca
            `video_fullframe_tb.v`, lo que devuelve `monitor.py read-block`
            desde la placa y lo que genera `make-framebuffer`.
  - `.hex`  medias palabras de 16 bits, una por linea, con comentarios `//`.
            Es lo que vuelca `video_fullframe_tb.v` en paralelo, para poder
            mirar un pixel concreto con un editor de texto.
  - `.ppm`  el que escribe `video_frame_tb.v` a resolucion reducida.

Y escribe cualquier formato que entienda Pillow, elegido por la extension:
`.jpg`, `.png`, `.bmp`...

Sobre el JPEG
-------------

Para MIRAR una captura esta bien. Para COMPARARLA no: es con perdidas, asi que
dos capturas identicas pueden dar ficheros distintos y dos distintas pueden dar
el mismo pixel. La comparacion se hace siempre sobre el `.bin` o el `.ppm`, con
`compare-frames.py`. Por eso esta herramienta convierte en un solo sentido.

Uso:

    frame-to-image.py frame_full.bin salida.jpg
    frame-to-image.py frame_full.hex salida.png --escala 2
    frame-to-image.py capturado.bin mirar.png --tamano 320x240
"""

import argparse
import sys
from pathlib import Path

ANCHO_POR_DEFECTO = 320
ALTO_POR_DEFECTO = 240


def expandir(valor: int) -> tuple[int, int, int]:
    """RGB565 a RGB888 replicando los bits altos.

    Es lo mismo que hace el scanout en RTL, y no es un detalle cosmetico: sin
    replicar, 0b11111 daria 0xf8 en vez de 0xff y el blanco saldria gris.
    """
    r5 = (valor >> 11) & 0x1F
    g6 = (valor >> 5) & 0x3F
    b5 = valor & 0x1F
    return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


def leer_bin(ruta: Path, ancho: int, alto: int) -> list:
    datos = ruta.read_bytes()
    esperado = ancho * alto * 2
    if len(datos) != esperado:
        raise ValueError(
            f"{ruta.name}: {len(datos)} bytes para {ancho}x{alto} en RGB565, "
            f"se esperaban {esperado}. ¿Es el tamano correcto? (--tamano)"
        )
    return [expandir(datos[i] | (datos[i + 1] << 8))
            for i in range(0, len(datos), 2)]


def leer_hex(ruta: Path, ancho: int, alto: int) -> list:
    valores = []
    for linea in ruta.read_text(encoding="ascii").splitlines():
        limpia = linea.split("//", 1)[0].strip()
        if limpia:
            valores.append(int(limpia, 16))
    if len(valores) != ancho * alto:
        raise ValueError(
            f"{ruta.name}: {len(valores)} palabras para {ancho}x{alto}, "
            f"se esperaban {ancho * alto}"
        )
    return [expandir(v) for v in valores]


def leer_ppm(ruta: Path) -> tuple[int, int, list]:
    tokens = []
    for linea in ruta.read_text(encoding="ascii").splitlines():
        tokens.extend(linea.split("#", 1)[0].split())
    if not tokens or tokens[0] != "P3":
        raise ValueError(f"{ruta.name}: no es un PPM de texto (P3)")
    ancho, alto = int(tokens[1]), int(tokens[2])
    valores = [int(t) for t in tokens[4:]]
    if len(valores) != ancho * alto * 3:
        raise ValueError(f"{ruta.name}: componentes incompletas")
    return ancho, alto, [tuple(valores[i:i + 3])
                         for i in range(0, len(valores), 3)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada")
    parser.add_argument("salida")
    parser.add_argument(
        "--tamano", default=f"{ANCHO_POR_DEFECTO}x{ALTO_POR_DEFECTO}",
        help="ANCHOxALTO del framebuffer; los PPM lo llevan dentro")
    parser.add_argument(
        "--escala", type=int, default=1,
        help="ampliar por un entero. 2 reproduce el escalado del scanout, que "
             "es como se ve en el monitor de verdad")
    args = parser.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("ERROR: falta Pillow. Esta en requirements.txt:", file=sys.stderr)
        print("    .venv\\Scripts\\pip install -r requirements.txt",
              file=sys.stderr)
        return 2

    entrada = Path(args.entrada)
    try:
        ancho, alto = (int(v) for v in args.tamano.lower().split("x"))
        sufijo = entrada.suffix.lower()
        if sufijo == ".ppm":
            ancho, alto, pixeles = leer_ppm(entrada)
        elif sufijo == ".hex":
            pixeles = leer_hex(entrada, ancho, alto)
        else:
            pixeles = leer_bin(entrada, ancho, alto)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    imagen = Image.new("RGB", (ancho, alto))
    imagen.putdata(pixeles)
    if args.escala > 1:
        # NEAREST y no otra cosa: interpolar un framebuffer de prueba
        # emborrona justo los bordes de un pixel, que es donde suelen estar los
        # errores que se quieren ver.
        imagen = imagen.resize((ancho * args.escala, alto * args.escala),
                               Image.NEAREST)

    salida = Path(args.salida)
    opciones = {"quality": 95} if salida.suffix.lower() in (".jpg", ".jpeg") else {}
    imagen.save(salida, **opciones)
    print(f"{ancho}x{alto}"
          f"{f' escalado a {ancho * args.escala}x{alto * args.escala}' if args.escala > 1 else ''}"
          f" -> {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
