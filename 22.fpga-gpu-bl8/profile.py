#!/usr/bin/env python3
"""Lee los contadores de rendimiento de la placa y los presenta como un perfil.

Los contadores viven en 0x80000300 (ver mmio.md). Existen precisamente para no
tener que simular: un frame entero de `plasma.asm` son ~3 millones de ciclos, y
simularlo en RTL tarda unos diez minutos. Aqui se lee en un parpadeo.

Uso tipico -- medir un programa de punta a punta:

    python profile.py --port COM3 --program examples/plasma.asm

Eso carga el programa, toma los contadores, lo ejecuta, los vuelve a tomar, y
presenta la diferencia. Sin --program, solo muestra el estado actual.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import serial

import monitor

BASE = 0x80000300

COUNTERS = [
    ("CYCLES", 0x00, "ciclos"),
    ("RETIRED", 0x04, "instrucciones retiradas"),
    ("IMEM_HITS", 0x08, "aciertos del bufer de instrucciones"),
    ("IMEM_MISSES", 0x0C, "fallos del bufer de instrucciones"),
    ("LSU_TX", 0x10, "transacciones de la LSU vectorial"),
    ("VIDEO_TX", 0x14, "transacciones del scanout"),
    ("STALL_MEM", 0x18, "ciclos con la LSU sin aceptar peticion"),
    ("LANE_OPS", 0x1C, "operaciones de hilo (suma de lanes activas)"),
]


def read_word(client: monitor.MonitorClient, address: int) -> int:
    data = client.read_block(address, 4)
    return int.from_bytes(data, "little")


def snapshot(client: monitor.MonitorClient) -> dict[str, int]:
    return {name: read_word(client, BASE + offset) for name, offset, _ in COUNTERS}


def report(before: dict[str, int], after: dict[str, int]) -> None:
    delta = {k: (after[k] - before[k]) & 0xFFFFFFFF for k in after}

    cycles = delta["CYCLES"]
    retired = delta["RETIRED"]
    fetches = delta["IMEM_HITS"] + delta["IMEM_MISSES"]

    print()
    print("=== PERFIL ===")
    for name, _, description in COUNTERS:
        print(f"  {name:<12} {delta[name]:>12,}   {description}")

    print()
    if cycles == 0:
        print("  No ha pasado nada: 0 ciclos.")
        return

    print(f"  tiempo a 25 MHz          {cycles / 25_000_000 * 1000:>9.1f} ms"
          f"   ({25_000_000 / cycles:>6.1f} fps si esto era un frame)")
    if retired:
        print(f"  ciclos por instruccion   {cycles / retired:>9.1f}")
    if fetches:
        print(f"  fallos de fetch          {delta['IMEM_MISSES'] / fetches * 100:>9.1f} %")

    # RETIRED cuenta instrucciones de WARP; LANE_OPS cuenta trabajo de HILO. La
    # division entre ambos dice cuanta divergencia hay: 8 es ninguna. Y la
    # utilizacion dice cuanto de las ocho ALU se esta usando de verdad.
    lane_ops = delta["LANE_OPS"]
    if retired and lane_ops:
        print(f"  lanes activas por instr  {lane_ops / retired:>9.2f}   de 8")
        print(f"  utilizacion de las ALU   {lane_ops / (cycles * 8) * 100:>9.1f} %")

    # Cada transaccion mueve 16 bytes. El coste en ciclos no se puede repartir
    # exactamente entre clientes porque el fabric los serializa, pero el numero
    # de transacciones si dice quien mueve el trafico.
    tx = delta["LSU_TX"] + delta["VIDEO_TX"] + delta["IMEM_MISSES"]
    if tx:
        print()
        print("  reparto del trafico de memoria (transacciones de 16 bytes):")
        for label, value in (("datos (LSU)", delta["LSU_TX"]),
                             ("scanout", delta["VIDEO_TX"]),
                             ("fetch", delta["IMEM_MISSES"])):
            print(f"    {label:<14} {value:>10,}  {value / tx * 100:>5.1f} %")
        print(f"    {'total':<14} {tx:>10,}  = {tx * 16 / 1024:,.0f} KiB")
        print(f"    ancho de banda {tx * 16 / (cycles / 25_000_000) / 1e6:>6.1f} MB/s"
              f"   (el canal da 23,5 MB/s)")

    if cycles and delta["STALL_MEM"]:
        print()
        print(f"  la LSU no pudo aceptar peticion el "
              f"{delta['STALL_MEM'] / cycles * 100:.1f} % de los ciclos")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=None)
    parser.add_argument("--program", default=None,
                        help="ensambla, carga y ejecuta este .asm antes de medir")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="segundos de espera a que el programa termine")
    args = parser.parse_args()

    # NO vale `available_ports().split(",")[0]`: eso devolvia el primer puerto
    # del sistema, que con la placa desenchufada es COM1 o un enlace Bluetooth.
    port = args.port or monitor.detect_port()

    with serial.Serial(port=port, baudrate=monitor.BAUDRATE,
                       bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                       stopbits=serial.STOPBITS_ONE, timeout=2.0,
                       write_timeout=2.0) as connection:
        client = monitor.MonitorClient(connection)

        if args.program:
            source = Path(args.program)
            binary = source.with_suffix(".bin")
            root = Path(__file__).resolve().parents[1]
            subprocess.run([sys.executable, str(root / "1.isa" / "miniisa_asm.py"),
                            str(source)], check=True)
            client.reset_cpu()
            client.write_memory(0, binary.read_bytes())

        before = snapshot(client)

        if args.program:
            client.run_cpu()
            deadline = time.time() + args.timeout
            while time.time() < deadline:
                if client.get_status().halted:
                    break
                time.sleep(0.05)
            else:
                print("AVISO: el programa no habia terminado al vencer el plazo;"
                      " el perfil incluye solo lo corrido hasta aqui.")
                client.halt_cpu()

        after = snapshot(client)

    report(before, after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
