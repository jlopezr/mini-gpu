#!/usr/bin/env python3
"""Modelo de referencia de `swap_demo.asm` y `swap_demo_fast.asm`.

Los dos programas dibujan LO MISMO --una banda verde de 16 lineas sobre fondo
azul, que baja dos pixeles por frame-- por dos caminos distintos:

  - `swap_demo.asm` repinta las 240 lineas enteras cada frame.
  - `swap_demo_fast.asm` solo toca 32 lineas: borra la banda vieja y dibuja la
    nueva, llevando la cuenta de donde quedo la banda en CADA buffer por
    separado.

Por eso los dos casos comparten este frame esperado. Y por eso el interesante
es el segundo: el fallo clasico del redibujo incremental --olvidar que hay dos
buffers y borrar usando la posicion del otro-- deja un rastro de bandas verdes
que no se borran nunca, y contra este fichero eso se ve como un fallo en vez de
como algo que hay que mirar a ojo.

## Por que la banda cae en esta linea

`run_until.swap` para tras el N-esimo intercambio COMPLETADO, y el backend
vuelca desde `FB_FRONT`. El bucle de los dos programas es:

    frame:  dibujar la banda en R21 sobre el buffer trasero
            SWAP = 1; esperar a que el hardware lo aplique
            R21 += 2; si R21 >= 224, R21 = 0

O sea que el intercambio numero N hace visible el buffer que se dibujo con el
valor de R21 ANTERIOR al incremento. Con R21 empezando en 0, tras el swap N se
ve la banda en `2*(N-1)`, y el `MOVI R21, 0` de la vuelta la hace periodica
cada 112 frames (R21 recorre 0, 2, ... 222).

Ese `-1` es el unico sitio donde este caso se puede equivocar en silencio: con
el desfase mal, el fichero seguiria siendo un frame perfectamente valido, solo
que de otro instante.

Uso:

    python reference.py            # escribe expected/frame.bin
    python reference.py --ppm x.ppm  # y ademas un PPM para mirarlo
"""

import argparse
from pathlib import Path

ANCHO = 320
ALTO = 240
# Colores RGB565, los mismos que usan los dos programas.
FONDO = 0x001F      # azul
BANDA = 0x07E0      # verde
BANDA_ALTO = 16
# `MOVI R22, 224` en los dos programas: 240 - BANDA_ALTO. R21 avanza de dos en
# dos y vuelve a cero al llegar, asi que el ciclo son 224/2 = 112 frames.
PERIODO = 112
# El de `test.json`. Si se cambia alli, hay que cambiarlo aqui.
SWAPS = 24


def banda_y(swaps: int) -> int:
    """Linea superior de la banda en el buffer visible tras `swaps` swaps."""
    return 2 * ((swaps - 1) % PERIODO)


def framebuffer(swaps: int = SWAPS) -> bytes:
    y0 = banda_y(swaps)
    datos = bytearray()
    for y in range(ALTO):
        color = BANDA if y0 <= y < y0 + BANDA_ALTO else FONDO
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
    parser.add_argument("--swaps", type=int, default=SWAPS)
    args = parser.parse_args()

    aqui = Path(__file__).resolve().parent
    (aqui / "expected").mkdir(exist_ok=True)
    datos = framebuffer(args.swaps)
    destino = aqui / "expected" / "frame.bin"
    destino.write_bytes(datos)
    print(f"banda en y={banda_y(args.swaps)}, {len(datos)} bytes -> {destino}")

    if args.ppm:
        escribir_ppm(Path(args.ppm), datos)
        print(f"y {args.ppm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
