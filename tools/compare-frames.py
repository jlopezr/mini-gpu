#!/usr/bin/env python3
"""Compara frames capturados contra una referencia, y dice DONDE fallan.

Capturar frames y mirarlos no es una prueba: es hacer capturas de pantalla. Lo
que convierte eso en una prueba es una referencia calculada por otro camino y un
fallo automatico. Esto es la segunda mitad.

Come frames de dos sitios:

  - PPM de texto, que es lo que vuelca `video_frame_tb.v` en simulacion;
  - binarios RGB565 de 320x240, que es lo que devuelve
    `monitor.py read-block 0x01000000 153600` desde la placa.

Y produce, cuando algo no cuadra, un PPM de diferencias con los pixeles malos en
magenta sobre el original atenuado. Un numero de pixeles distintos no dice nada;
ver que las diferencias forman una banda horizontal, o la mitad de abajo, o una
columna, dice inmediatamente que clase de fallo es.

Uso
---

    compare-frames.py esperado.ppm obtenido.ppm
    compare-frames.py --rgb565 320x240 esperado.bin capturado.bin
    compare-frames.py --tolerancia 2 a.ppm b.ppm

Codigo de salida 0 si son iguales, 1 si no. Pensado para encadenar en un script
de pruebas.
"""

import argparse
import sys
from pathlib import Path


def leer_ppm(ruta):
    """Lee un PPM de texto (P3). Devuelve (ancho, alto, [(r,g,b), ...])."""
    tokens = []
    with open(ruta, "r", encoding="ascii") as f:
        for linea in f:
            # Los comentarios de PPM empiezan por '#'.
            sin_comentario = linea.split("#", 1)[0]
            tokens.extend(sin_comentario.split())

    if not tokens or tokens[0] != "P3":
        raise ValueError(f"{ruta}: no es un PPM de texto (P3)")
    ancho, alto, maximo = int(tokens[1]), int(tokens[2]), int(tokens[3])
    if maximo != 255:
        raise ValueError(f"{ruta}: solo se admite maximo 255, no {maximo}")

    valores = [int(t) for t in tokens[4:]]
    esperados = ancho * alto * 3
    if len(valores) != esperados:
        raise ValueError(
            f"{ruta}: {len(valores)} componentes para {ancho}x{alto}, "
            f"se esperaban {esperados}"
        )
    pixeles = [tuple(valores[i:i + 3]) for i in range(0, len(valores), 3)]
    return ancho, alto, pixeles


def leer_rgb565(ruta, ancho, alto):
    """Lee un volcado crudo de framebuffer RGB565, little-endian.

    Es el formato que devuelve `monitor.py read-block`, y el mismo que genera
    `make-framebuffer`. Se expande a 8 bits por componente replicando los
    bits altos, exactamente como hace el scanout en RTL: sin eso, 5'b11111
    saldria 0xf8 en vez de 0xff y TODOS los pixeles claros pareceran distintos.
    """
    datos = Path(ruta).read_bytes()
    esperado = ancho * alto * 2
    if len(datos) != esperado:
        raise ValueError(
            f"{ruta}: {len(datos)} bytes para {ancho}x{alto} en RGB565, "
            f"se esperaban {esperado}"
        )

    pixeles = []
    for i in range(0, len(datos), 2):
        valor = datos[i] | (datos[i + 1] << 8)
        r5 = (valor >> 11) & 0x1F
        g6 = (valor >> 5) & 0x3F
        b5 = valor & 0x1F
        pixeles.append((
            (r5 << 3) | (r5 >> 2),
            (g6 << 2) | (g6 >> 4),
            (b5 << 3) | (b5 >> 2),
        ))
    return ancho, alto, pixeles


def escribir_ppm(ruta, ancho, alto, pixeles):
    with open(ruta, "w", encoding="ascii") as f:
        f.write(f"P3\n{ancho} {alto}\n255\n")
        for r, g, b in pixeles:
            f.write(f"{r} {g} {b}\n")


def describir_region(malos, ancho, alto):
    """Resume DONDE estan las diferencias, que es lo que dice que fallo.

    Un recuento de pixeles distintos no orienta. Saber que ocupan un rectangulo
    de una fila, o la mitad inferior, o una columna, apunta directamente a un
    error de pitch, a un desgarro o a un fallo de banco.
    """
    xs = [p % ancho for p in malos]
    ys = [p // ancho for p in malos]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    filas = len(set(ys))
    columnas = len(set(xs))

    partes = [f"rectangulo x {x0}..{x1}, y {y0}..{y1}"]
    if filas == 1:
        partes.append("una sola fila: huele a error de pitch o de linea")
    elif columnas == 1:
        partes.append("una sola columna: huele a error de indice de pixel")
    elif y0 == 0 and y1 == alto - 1 and len(malos) == ancho * alto:
        partes.append("el frame entero")
    elif y0 > 0 and y1 == alto - 1:
        partes.append(
            f"desde la fila {y0} hasta el final: huele a desgarro o a un swap "
            "a mitad de frame"
        )
    return "; ".join(partes)


def comparar(a, b, tolerancia):
    ancho_a, alto_a, pix_a = a
    ancho_b, alto_b, pix_b = b
    if (ancho_a, alto_a) != (ancho_b, alto_b):
        print(
            f"FALLO: tamanos distintos, {ancho_a}x{alto_a} contra "
            f"{ancho_b}x{alto_b}"
        )
        return None

    malos = []
    for i, (pa, pb) in enumerate(zip(pix_a, pix_b)):
        if any(abs(ca - cb) > tolerancia for ca, cb in zip(pa, pb)):
            malos.append(i)
    return malos


def main():
    parser = argparse.ArgumentParser(
        description="Compara dos frames y dice donde difieren.")
    parser.add_argument("esperado")
    parser.add_argument("obtenido")
    parser.add_argument(
        "--rgb565", metavar="ANCHOxALTO",
        help="los dos ficheros son volcados crudos RGB565 de ese tamano")
    parser.add_argument(
        "--tolerancia", type=int, default=0,
        help="diferencia maxima admitida por componente (por defecto 0)")
    parser.add_argument(
        "--diff", metavar="FICHERO",
        help="escribe un PPM con las diferencias en magenta")
    parser.add_argument(
        "--max-listados", type=int, default=8,
        help="cuantos pixeles distintos listar (por defecto 8)")
    args = parser.parse_args()

    try:
        if args.rgb565:
            ancho, alto = (int(v) for v in args.rgb565.lower().split("x"))
            a = leer_rgb565(args.esperado, ancho, alto)
            b = leer_rgb565(args.obtenido, ancho, alto)
        else:
            a = leer_ppm(args.esperado)
            b = leer_ppm(args.obtenido)
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}")
        return 2

    malos = comparar(a, b, args.tolerancia)
    if malos is None:
        return 1

    ancho, alto, pix_a = a
    _, _, pix_b = b
    total = ancho * alto

    if not malos:
        print(f"OK: {ancho}x{alto}, {total} pixeles identicos")
        return 0

    porcentaje = 100.0 * len(malos) / total
    print(f"FALLO: {len(malos)} de {total} pixeles distintos ({porcentaje:.2f} %)")
    print(f"  {describir_region(malos, ancho, alto)}")
    for i in malos[:args.max_listados]:
        x, y = i % ancho, i // ancho
        print(f"  ({x:4d},{y:4d})  esperado {pix_a[i]}  obtenido {pix_b[i]}")
    if len(malos) > args.max_listados:
        print(f"  ... y {len(malos) - args.max_listados} mas")

    if args.diff:
        conjunto = set(malos)
        salida = [
            (255, 0, 255) if i in conjunto else tuple(c // 3 for c in p)
            for i, p in enumerate(pix_b)
        ]
        escribir_ppm(args.diff, ancho, alto, salida)
        print(f"  diferencias en magenta: {args.diff}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
