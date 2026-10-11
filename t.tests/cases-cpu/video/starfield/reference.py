#!/usr/bin/env python3
"""Modelo de referencia de `starfield.asm`: el campo de estrellas.

Calcula el framebuffer que debe estar visible tras el intercambio N y lo
escribe en `expected/frame.bin`.

Es un modelo, no una captura. Si el fichero esperado se generara leyendo la
placa, el caso solo comprobaria que la placa sigue haciendo lo que hacia,
incluido lo que haga mal. Aqui el campo entero se recalcula desde cero --el
mismo xorshift32, el mismo orden de tiradas, la misma proyeccion-- escrito de
forma independiente del ensamblador.

Que este caso comprueba y los otros de video no
-----------------------------------------------

`DIV` con dividendo negativo, 256 veces por frame y con el resultado puesto
directamente en una coordenada de pantalla. Un truncamiento hacia el cero mal
implementado --hacia menos infinito, por ejemplo-- desplaza un pixel las
estrellas de la mitad izquierda y de la mitad superior, y solo esas. Eso no lo
ve ningun caso de ALU que compare cocientes sueltos, porque ahi el signo del
resultado se mira pero no su reparto espacial.

Tambien fija el contrato del PRNG: si alguien toca el xorshift, el campo entero
cambia y el caso lo dice.

Uso:

    python reference.py                  # el intercambio por defecto
    python reference.py --swap 40        # otro
    python reference.py --ppm x.ppm      # y un PPM para mirarlo
    python reference.py --censo          # cuantas estrellas se ven y cuantas renacen
"""

import argparse
from pathlib import Path

ANCHO = 320
ALTO = 240
CX = 160
CY = 120

N_ESTRELLAS = 256
Z_MIN = 128
Z_MAX = 1151
PASO = 6                   # unidades de z por frame

SEMILLA = 0x12345678       # no puede ser cero: xorshift se clava en el cero
MASCARA = 0xFFFFFFFF

# Grises RGB565 por tramo de profundidad. Los cortes reparten [Z_MIN, Z_MAX]
# en tres tramos parecidos.
CORTE_CERCA = 400
CORTE_MEDIO = 800
COLOR_CERCA = 0xFFFF
COLOR_MEDIO = 0x9492
COLOR_LEJOS = 0x4208

# El intercambio en el que para el caso. Para el 40 ya han renacido estrellas
# --la primera lo hace hacia el frame 1-- asi que el caso cubre el camino de
# reaparicion y no solo el de acercamiento.
SWAP_POR_DEFECTO = 40


class Xorshift:
    """El mismo generador que `rnd` en el ensamblador."""

    def __init__(self, semilla: int = SEMILLA) -> None:
        self.estado = semilla

    def siguiente(self) -> int:
        x = self.estado
        x ^= (x << 13) & MASCARA
        x ^= x >> 17
        x ^= (x << 5) & MASCARA
        self.estado = x & MASCARA
        return self.estado


def alto16(valor: int) -> int:
    """Los 16 bits altos, extendidos en signo: el `SARI 16` del ensamblador.

    Son los altos y no los bajos a proposito. En xorshift32 los bits bajos son
    de peor calidad, y en un campo de estrellas eso se ve como una rejilla.
    """
    alto = valor >> 16
    return alto - 65536 if alto >= 32768 else alto


def sembrar(rng: Xorshift) -> list[list[int]]:
    """El campo inicial, en el mismo orden de tiradas que `seed_loop`.

    Por estrella son tres tiradas y en este orden: primero la z, luego la x y
    luego la y. El orden importa tanto como la formula: cambiarlo da otro campo
    igual de valido y otro fichero esperado.
    """
    estrellas = []
    for _ in range(N_ESTRELLAS):
        z = (rng.siguiente() & 1023) + Z_MIN
        x = alto16(rng.siguiente())
        y = alto16(rng.siguiente())
        estrellas.append([x, y, z])
    return estrellas


def div_trunc(a: int, b: int) -> int:
    """Division entera truncando hacia cero, como `DIV` de la ISA.

    La de Python trunca hacia menos infinito, que para las estrellas de x
    negativa daria un pixel de diferencia. Es exactamente el fallo que este
    caso existe para detectar, asi que el modelo no puede heredarlo.
    """
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def avanzar(estrellas: list[list[int]], rng: Xorshift) -> list[tuple[int, int, int]]:
    """Un frame: acerca todas las estrellas y devuelve los pixeles a pintar.

    Mismo orden que el ensamblador: la que se pasa de largo renace y NO se
    dibuja en este frame.
    """
    pixeles = []
    for estrella in estrellas:
        z = estrella[2] - PASO
        if z < Z_MIN:
            # Renace al fondo. La z es Z_MAX fija, no aleatoria: solo se tiran
            # dados para x e y, y en ese orden.
            estrella[0] = alto16(rng.siguiente())
            estrella[1] = alto16(rng.siguiente())
            estrella[2] = Z_MAX
            continue
        estrella[2] = z

        sx = CX + div_trunc(estrella[0], z)
        sy = CY + div_trunc(estrella[1], z)
        if not (0 <= sx < ANCHO and 0 <= sy < ALTO):
            continue

        if z < CORTE_CERCA:
            color = COLOR_CERCA
        elif z < CORTE_MEDIO:
            color = COLOR_MEDIO
        else:
            color = COLOR_LEJOS
        pixeles.append((sx, sy, color))
    return pixeles


def simular(swap: int) -> list[tuple[int, int, int]]:
    """Los pixeles visibles tras el intercambio N.

    El programa dibuja el frame N y DESPUES pide el intercambio N, asi que lo
    que se ve tras el intercambio N es el frame N, no el N-1. Es distinto de
    `bounce`, que mueve despues de intercambiar.
    """
    rng = Xorshift()
    estrellas = sembrar(rng)
    pixeles: list[tuple[int, int, int]] = []
    for _ in range(swap):
        pixeles = avanzar(estrellas, rng)
    return pixeles


def framebuffer(pixeles) -> bytes:
    datos = bytearray(ANCHO * ALTO * 2)      # fondo negro
    for sx, sy, color in pixeles:
        desplazamiento = (sy * ANCHO + sx) * 2
        datos[desplazamiento] = color & 0xFF
        datos[desplazamiento + 1] = (color >> 8) & 0xFF
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


def censo(swap: int) -> None:
    """Cuantas estrellas se ven y cuantas renacen, frame a frame.

    Sirve para elegir el intercambio del caso con criterio en vez de a ojo: el
    que se elija tiene que haber visto ya reaparecer estrellas.
    """
    rng = Xorshift()
    estrellas = sembrar(rng)
    total_renacidas = 0
    for frame in range(1, swap + 1):
        antes = [e[2] for e in estrellas]
        pixeles = avanzar(estrellas, rng)
        renacidas = sum(1 for z, e in zip(antes, estrellas) if e[2] == Z_MAX and z - PASO < Z_MIN)
        total_renacidas += renacidas
        if renacidas or frame >= swap - 2 or frame <= 2:
            print(f"  frame {frame:3d}: {len(pixeles):3d} visibles, "
                  f"{renacidas} renacidas (acumuladas {total_renacidas})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swap", type=int, default=SWAP_POR_DEFECTO)
    parser.add_argument("--ppm")
    parser.add_argument("--censo", action="store_true",
                        help="estrellas visibles y reapariciones, frame a frame")
    args = parser.parse_args()

    if args.censo:
        censo(args.swap)
        return 0

    aqui = Path(__file__).resolve().parent
    (aqui / "expected").mkdir(exist_ok=True)
    pixeles = simular(args.swap)
    datos = framebuffer(pixeles)
    destino = aqui / "expected" / "frame.bin"
    destino.write_bytes(datos)
    print(f"intercambio {args.swap}: {len(pixeles)} estrellas visibles")
    print(f"{len(datos)} bytes -> {destino}")

    if args.ppm:
        escribir_ppm(Path(args.ppm), datos)
        print(f"y {args.ppm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
