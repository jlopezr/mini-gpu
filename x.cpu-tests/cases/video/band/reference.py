#!/usr/bin/env python3
"""Modelo de referencia del framebuffer que debe producir `band.asm`.

Genera el fichero `expected/frame.bin` contra el que se compara la captura de la
placa. Es lo que convierte «capturar un frame» en una prueba: sin una referencia
calculada **por otro camino**, comparar la captura contra otra captura solo
comprueba que la placa sigue haciendo lo que hacia, incluido lo que haga mal.

El repositorio ya tenia el precedente bueno: el README de la 16 cuenta que la
logica de borrado de swap_demo_fast se valido modelando el algoritmo en Python
y, sobre todo, comprobando que la version ingenua falla en el frame 2.

Uso:

    python reference.py            # escribe expected/frame.bin
    python reference.py --ppm x.ppm  # y ademas un PPM para mirarlo
"""

import argparse
from pathlib import Path

ANCHO = 320
ALTO = 240
# Colores RGB565, los mismos que usa el programa.
FONDO = 0x001F      # azul
BANDA = 0x07E0      # verde
# La banda ocupa estas lineas. `band.asm` las tiene fijas: el caso no mueve la
# banda entre frames a proposito, para que el frame esperado no dependa de
# cuantos intercambios hayan pasado.
BANDA_Y0 = 96
BANDA_ALTO = 16


def framebuffer() -> bytes:
    datos = bytearray()
    for y in range(ALTO):
        color = BANDA if BANDA_Y0 <= y < BANDA_Y0 + BANDA_ALTO else FONDO
        datos.extend(color.to_bytes(2, "little") * ANCHO)
    return bytes(datos)


def escribir_ppm(ruta: Path, datos: bytes) -> None:
    with open(ruta, "w", encoding="ascii") as f:
        f.write(f"P3\n{ANCHO} {ALTO}\n255\n")
        for i in range(0, len(datos), 2):
            valor = datos[i] | (datos[i + 1] << 8)
            r5, g6, b5 = (valor >> 11) & 0x1F, (valor >> 5) & 0x3F, valor & 0x1F
            # Replicar los bits altos, igual que el scanout en RTL: sin eso
            # 0b11111 daria 0xf8 en vez de 0xff.
            f.write(f"{(r5 << 3) | (r5 >> 2)} {(g6 << 2) | (g6 >> 4)} "
                    f"{(b5 << 3) | (b5 >> 2)}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ppm", help="escribe ademas un PPM para mirarlo")
    args = parser.parse_args()

    aqui = Path(__file__).resolve().parent
    (aqui / "expected").mkdir(exist_ok=True)
    datos = framebuffer()
    destino = aqui / "expected" / "frame.bin"
    destino.write_bytes(datos)
    print(f"{len(datos)} bytes -> {destino}")

    if args.ppm:
        escribir_ppm(Path(args.ppm), datos)
        print(f"y {args.ppm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
