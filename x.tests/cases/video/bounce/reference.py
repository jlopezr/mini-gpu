#!/usr/bin/env python3
"""Modelo de referencia de `bounce.asm`: el cuadrado que rebota.

Calcula el framebuffer que debe estar visible tras el intercambio N y lo
escribe en `expected/frame.bin`.

Es un modelo, no una captura. Si el fichero esperado se generara leyendo la
placa, el caso solo comprobaria que la placa sigue haciendo lo que hacia,
incluido lo que haga mal. Aqui la posicion se recalcula desde cero con la misma
regla que el programa en ensamblador, escrita de forma independiente.

Uso:

    python reference.py                # el intercambio por defecto
    python reference.py --swap 80      # otro
    python reference.py --ppm x.ppm    # y un PPM para mirarlo
    python reference.py --trayectoria  # imprime las posiciones, para revisarlas
"""

import argparse
from pathlib import Path

ANCHO = 320
ALTO = 240
LADO = 32                  # el cuadrado es de 32x32
PASO = 4                   # pixeles por frame, en cada eje
FONDO = 0x001F             # azul
CUADRADO = 0xFFFF          # blanco

X_MAX = ANCHO - LADO       # 288
Y_MAX = ALTO - LADO        # 208

# El intercambio en el que para el caso. Se elige para que los DOS rebotes ya
# hayan ocurrido: con paso 4, la y llega a 208 en el paso 52 y la x a 288 en el
# 72. Parando en el 80 se ha rebotado en los dos ejes, que es lo que hace que
# el caso pruebe los bordes y no solo el movimiento.
SWAP_POR_DEFECTO = 80


def posicion(paso: int) -> tuple[int, int]:
    """Posicion del cuadrado en el paso indicado, contando desde (0,0).

    Misma regla que el ensamblador: avanzar y, si se sale, pegarse al borde e
    invertir. Con `PASO` divisor exacto de `X_MAX` y de `Y_MAX` el cuadrado cae
    justo en el borde y no hace falta recortar, pero el recorte se escribe
    igualmente porque el ensamblador tambien lo lleva: si alguien cambia el
    paso, los dos tienen que seguir coincidiendo.

    El cuadrado se queda UN paso pegado a la pared: el paso que le lleva justo
    al maximo no invierte todavia --no se ha pasado-- y el siguiente si. Es
    consecuencia de recortar y luego invertir, en vez de reflejar. No es un
    fallo: es determinista, los dos ejes lo hacen igual y el ensamblador
    tambien. Se deja asi porque reflejar costaria una resta mas en el
    ensamblador sin mejorar lo que el caso prueba.
    """
    x = y = 0
    dx = dy = PASO
    for _ in range(paso):
        x += dx
        if x < 0:
            x, dx = 0, -dx
        elif x > X_MAX:
            x, dx = X_MAX, -dx
        y += dy
        if y < 0:
            y, dy = 0, -dy
        elif y > Y_MAX:
            y, dy = Y_MAX, -dy
    return x, y


def framebuffer(swap: int) -> bytes:
    # El programa dibuja, intercambia y DESPUES mueve, asi que lo que se ve
    # tras el intercambio N es la posicion del paso N-1.
    x, y = posicion(swap - 1)
    fondo = FONDO.to_bytes(2, "little")
    cuadrado = CUADRADO.to_bytes(2, "little")

    datos = bytearray()
    for fila in range(ALTO):
        if y <= fila < y + LADO:
            datos.extend(fondo * x)
            datos.extend(cuadrado * LADO)
            datos.extend(fondo * (ANCHO - x - LADO))
        else:
            datos.extend(fondo * ANCHO)
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
    parser.add_argument("--trayectoria", action="store_true",
                        help="imprime las posiciones y donde rebota")
    args = parser.parse_args()

    if args.trayectoria:
        anterior = posicion(0)
        for paso in range(1, args.swap + 1):
            actual = posicion(paso)
            marcas = []
            if actual[0] in (0, X_MAX):
                marcas.append("rebote en x")
            if actual[1] in (0, Y_MAX):
                marcas.append("rebote en y")
            if marcas or paso >= args.swap - 2:
                print(f"  paso {paso:3d}: {actual}  {', '.join(marcas)}")
            anterior = actual
        return 0

    aqui = Path(__file__).resolve().parent
    (aqui / "expected").mkdir(exist_ok=True)
    datos = framebuffer(args.swap)
    destino = aqui / "expected" / "frame.bin"
    destino.write_bytes(datos)
    x, y = posicion(args.swap - 1)
    print(f"intercambio {args.swap}: cuadrado en ({x},{y})")
    print(f"{len(datos)} bytes -> {destino}")

    if args.ppm:
        escribir_ppm(Path(args.ppm), datos)
        print(f"y {args.ppm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
