#!/usr/bin/env python3
"""Matriz beat x DQ de la SDRAM, contra la placa.

Escribe un unico 1 aislado en cada una de las 128 posiciones de una rafaga
(8 beats de 16 bits) y comprueba que vuelve donde se puso. Repite el barrido en
varias direcciones.

POR QUE EXISTE ESTO Y NO BASTA UN BANCO DE PRUEBAS
--------------------------------------------------

El camino de lectura de DQ entra por un pin. `nextpnr` no modela lo que pasa
fuera del chip, asi que su `Fmax` puede dar +14,5% de holgura con el diseno
roto --paso exactamente eso--. Y el modelo de SDRAM comparte el parametro
`READ_DELAY_CYCLES` con el controlador: emparejados leen bien con cualquier
valor, asi que la simulacion comprueba coherencia consigo misma, no con la
placa.

Lo que si distingue esta matriz:

  - todo limpio            -> la captura esta centrada en el ojo;
  - casillas fijas malas   -> desfase de un beat entero, o un bit muerto;
  - casillas que CAMBIAN al recompilar con otra semilla -> margen de captura.

Esa ultima fue la que resolvio el caso: con captura en flanco de subida salian
(3,4) (3,5) (7,4) (7,5) con una semilla y (0,6) (3,4) (3,6) (4,6) (6,6) (7,4)
(7,6) con otra. Un fallo que se mueve con la colocacion no es logica.

Uso:

    python sdram_dq_matrix.py --port COM3
    python sdram_dq_matrix.py --port COM3 --direcciones 0x3000 0x100000
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import serial

import monitor

BEATS = 8
DQ = 16
DIRECCIONES_POR_DEFECTO = (0x3000, 0x3010, 0x4000, 0x100000)


def barrer(cliente, base: int) -> list[tuple[int, int]]:
    """Devuelve las casillas (beat, dq) que no vuelven intactas."""
    malas = []
    for beat in range(BEATS):
        for dq in range(DQ):
            datos = bytearray(2 * BEATS)
            struct.pack_into("<H", datos, 2 * beat, 1 << dq)
            cliente.write_memory(base, bytes(datos))
            if cliente.read_memory(base, 2 * BEATS) != bytes(datos):
                malas.append((beat, dq))
    return malas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument(
        "--direcciones", type=lambda v: int(v, 0), nargs="+",
        default=list(DIRECCIONES_POR_DEFECTO),
        help="direcciones base del barrido (alineadas a 16 bytes)")
    args = parser.parse_args()

    for base in args.direcciones:
        if base % 16:
            parser.error(f"0x{base:x} no esta alineada a 16 bytes")

    total = 0
    with serial.Serial(args.port, 1_000_000, timeout=args.timeout) as puerto:
        cliente = monitor.MonitorClient(puerto)
        # La memoria es del monitor solo con la CPU parada.
        cliente.halt_cpu()
        for base in args.direcciones:
            malas = barrer(cliente, base)
            total += len(malas)
            detalle = " ".join(f"({b},{d})" for b, d in malas) or "-"
            print(f"0x{base:08x}: {len(malas):3d} malas  {detalle}")

    print()
    if total == 0:
        print(f"OK: {BEATS * DQ} casillas limpias en "
              f"{len(args.direcciones)} direccion(es)")
        return 0
    print(f"FALLO: {total} casilla(s) mal. Si al recompilar con otra semilla")
    print("salen casillas DISTINTAS, es margen de captura y no logica:")
    print("mirar READ_DELAY_CYCLES y `dq_negedge` en sdram_controller_128.v.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
