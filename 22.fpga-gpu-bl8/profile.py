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

# Registros de video (ver mmio.md). Los mismos valores que pone
# gpu_profile_tb.v: si placa y banco no preparan lo mismo, no estan midiendo lo
# mismo y comparar sus numeros no significa nada.
VIDEO_CTRL = 0x80000200
FB_FRONT = 0x80000204
FB_BACK = 0x80000208
MODE_SCANOUT = 2

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


def write_word(client: monitor.MonitorClient, address: int, value: int) -> None:
    client.write_memory(address, value.to_bytes(4, "little"))


def setup_video(client: monitor.MonitorClient, front: int, back: int) -> None:
    """Prepara los dos buffers y enciende el scanout.

    Hace falta de verdad: tras el reset FB_FRONT y FB_BACK valen CERO, y
    plasma.asm se trae FB_BACK con un LOAD para saber donde dibujar. Sin esto
    el programa escribe los pixeles en la direccion 0 -- es decir, ENCIMA DE SI
    MISMO -- y unas instrucciones despues ejecuta basura y para con
    ERROR_MEMORY_ACCESS. El banco de pruebas si lo preparaba, y por eso el
    fallo solo salia en placa.
    """
    write_word(client, FB_FRONT, front)
    write_word(client, FB_BACK, back)
    write_word(client, VIDEO_CTRL, MODE_SCANOUT)


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
    parser.add_argument("--fb-front", type=lambda s: int(s, 0), default=0x0010_0000,
                        help="buffer que se muestra (por defecto 0x100000)")
    parser.add_argument("--fb-back", type=lambda s: int(s, 0), default=0x0014_0000,
                        help="buffer que se dibuja (por defecto 0x140000)")
    parser.add_argument("--no-video", action="store_true",
                        help="no tocar los registros de video (para programas"
                             " que no dibujan, o que se configuran solos)")
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
            # Despues del reset, y antes de arrancar: el reset del nucleo no
            # toca los registros de video, pero el programa lee FB_BACK nada
            # mas empezar.
            if not args.no_video:
                setup_video(client, args.fb_front, args.fb_back)

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
        status = client.get_status()

    report(before, after)

    # Un programa que ha reventado tambien produce contadores, y salen tan
    # convincentes como los buenos: la primera medida real dio 341
    # instrucciones y un CPI de 11.730 sin decir en ningun sitio que la GPU
    # habia parado con error. El perfil de un programa roto no vale nada, asi
    # que hay que decirlo y devolver fallo.
    if status.error:
        print()
        print(f"!! la GPU paro CON ERROR (codigo {status.error_code:#04x}, "
              f"pc={status.pc:#010x}): estos numeros NO son un perfil valido.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
