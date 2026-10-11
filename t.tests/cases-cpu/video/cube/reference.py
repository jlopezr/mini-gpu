#!/usr/bin/env python3
"""Modelo de referencia de `cube.asm`: el cubo en alambre girando.

Calcula el framebuffer que debe estar visible tras el intercambio N y lo
escribe en `expected/frame.bin`.

Es un modelo, no una captura. Aqui eso importa mas que en los otros casos de
video, porque el programa depende de tres semanticas enteras que es facil
implementar "casi bien":

- `MULFX` desplaza el producto de 64 bits ARITMETICAMENTE, o sea hacia menos
  infinito, no truncando hacia cero;
- `SARI` hace lo mismo con el valor;
- `DIV`, en cambio, SI trunca hacia cero.

Mezclar las dos reglas desplaza un pixel las aristas del lado negativo y solo
esas. Este modelo las escribe por separado y a proposito.

Uso:

    python reference.py                  # el intercambio por defecto
    python reference.py --swap 24        # otro
    python reference.py --ppm x.ppm      # y un PPM para mirarlo
    python reference.py --vertices       # los 8 puntos proyectados, para revisarlos
"""

import argparse
import math
from pathlib import Path

ANCHO = 320
ALTO = 240
CX, CY = 160, 120

UNO = 1 << 16
DZ = 3 * UNO               # camara a z = 3.0, Q16.16
K = 140                    # escala de proyeccion, en pixeles

# El programa dibuja el frame con los angulos de la iteracion y DESPUES pide el
# intercambio, asi que tras el intercambio N se ve la iteracion N, que uso
# a = N-1 y b = 3*(N-1).
PASO_A = 1
PASO_B = 3

SWAP_POR_DEFECTO = 24

# (x, y, z) en Q16.16. Mismo orden que la tabla `vertices` del ensamblador.
VERTICES = [
    (-UNO, -UNO, -UNO), (UNO, -UNO, -UNO), (-UNO, UNO, -UNO), (UNO, UNO, -UNO),
    (-UNO, -UNO,  UNO), (UNO, -UNO,  UNO), (-UNO, UNO,  UNO), (UNO, UNO,  UNO),
]

CYAN, MAGENTA, BLANCO = 0x07FF, 0xF81F, 0xFFFF

# Mismo orden que la tabla `edges`. El orden importa: donde dos aristas se
# cruzan, gana la ultima que pasa por el pixel.
ARISTAS = [
    (0, 1, CYAN), (1, 3, CYAN), (3, 2, CYAN), (2, 0, CYAN),
    (4, 5, MAGENTA), (5, 7, MAGENTA), (7, 6, MAGENTA), (6, 4, MAGENTA),
    (0, 4, BLANCO), (1, 5, BLANCO), (2, 6, BLANCO), (3, 7, BLANCO),
]

SENO = [int(round(math.sin(2 * math.pi * i / 256) * UNO)) for i in range(256)]


def mulfx(a: int, b: int) -> int:
    """`MULFX`: producto signed de 64 bits, desplazado ARITMETICAMENTE 16.

    `>>` de Python sobre enteros con signo ya es el desplazamiento aritmetico,
    o sea floor. No es lo mismo que truncar hacia cero y aqui la diferencia se
    ve en pantalla.
    """
    return (a * b) >> 16


def div_trunc(a: int, b: int) -> int:
    """`DIV`: division entera truncando HACIA CERO. La de Python no lo hace."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def proyectar(swap: int):
    """Los ocho vertices proyectados, tal y como los deja `vertex_loop`."""
    iteracion = swap - 1
    a = (iteracion * PASO_A) & 255
    b = (iteracion * PASO_B) & 255
    sa, ca = SENO[a], SENO[(a + 64) & 255]
    sb, cb = SENO[b], SENO[(b + 64) & 255]

    puntos = []
    for (x, y, z) in VERTICES:
        y1 = mulfx(y, ca) - mulfx(z, sa)
        z1 = mulfx(y, sa) + mulfx(z, ca)
        x2 = mulfx(x, cb) + mulfx(z1, sb)
        z2 = mulfx(z1, cb) - mulfx(x, sb)

        xi = x2 >> 8                 # SARI 8
        yi = y1 >> 8
        zi = (z2 + DZ) >> 8          # siempre > 0, ver cabecera de cube.asm

        puntos.append((CX + div_trunc(xi * K, zi),
                       CY + div_trunc(yi * K, zi)))
    return puntos


def recta(x0: int, y0: int, x1: int, y1: int):
    """Bresenham de los ocho octantes, igual que `drawline`.

    `dy` se lleva negado y el signo de cero es positivo, exactamente como el
    ensamblador: `BGE dy, 0` manda a la rama que lo niega.
    """
    dx = x1 - x0
    sx = 1
    if dx < 0:
        dx, sx = -dx, -1

    dy = y1 - y0
    if dy >= 0:
        sy, dy = 1, -dy
    else:
        sy = -1

    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def framebuffer(swap: int) -> bytes:
    puntos = proyectar(swap)
    datos = bytearray(ANCHO * ALTO * 2)      # todo negro: el programa limpia
    for i0, i1, color in ARISTAS:            # los dos buffers al arrancar
        x0, y0 = puntos[i0]
        x1, y1 = puntos[i1]
        for x, y in recta(x0, y0, x1, y1):
            desplazamiento = (y * ANCHO + x) * 2
            datos[desplazamiento] = color & 0xFF
            datos[desplazamiento + 1] = color >> 8
    return bytes(datos)


def escribir_ppm(ruta: Path, datos: bytes) -> None:
    with open(ruta, "w", encoding="ascii") as f:
        f.write(f"P3\n{ANCHO} {ALTO}\n255\n")
        for i in range(0, len(datos), 2):
            valor = datos[i] | (datos[i + 1] << 8)
            r5, g6, b5 = (valor >> 11) & 0x1F, (valor >> 5) & 0x3F, valor & 0x1F
            # Replicar los bits altos, igual que el scanout en RTL.
            f.write(f"{(r5 << 3) | (r5 >> 2)} {(g6 << 2) | (g6 >> 4)} "
                    f"{(b5 << 3) | (b5 >> 2)}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swap", type=int, default=SWAP_POR_DEFECTO)
    parser.add_argument("--ppm")
    parser.add_argument("--vertices", action="store_true",
                        help="los ocho puntos proyectados y la caja que ocupan")
    args = parser.parse_args()

    if args.vertices:
        puntos = proyectar(args.swap)
        for i, (x, y) in enumerate(puntos):
            print(f"  v{i}: ({x:3d}, {y:3d})")
        xs = [p[0] for p in puntos]
        ys = [p[1] for p in puntos]
        print(f"  caja: x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
        return 0

    aqui = Path(__file__).resolve().parent
    (aqui / "expected").mkdir(exist_ok=True)
    datos = framebuffer(args.swap)
    destino = aqui / "expected" / "frame.bin"
    destino.write_bytes(datos)
    encendidos = sum(1 for i in range(0, len(datos), 2)
                     if datos[i] or datos[i + 1])
    print(f"intercambio {args.swap}: {encendidos} pixeles encendidos")
    print(f"{len(datos)} bytes -> {destino}")

    if args.ppm:
        escribir_ppm(Path(args.ppm), datos)
        print(f"y {args.ppm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
