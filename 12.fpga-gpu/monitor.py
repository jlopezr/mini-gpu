#!/usr/bin/env python3
"""MiniGPU UART client: unified RAM, warp launch configuration and lane debug."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import serial

BAUDRATE = 250_000
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0xFFFF_FFFF
# Memoria que ve el programa: la única contra la que se valida un caso de test.
ARCHITECTURAL_REGIONS = (
    (0x0000_0000, 0x0002_0000),
)
# Ventanas de configuración y depuración, accesibles solo desde el monitor.
# Gemela de las ventanas que top.v pasa al monitor: las dos tienen que decir lo
# mismo. Desde que monitor.v es copia identica en 12, 14, 17 y 22, la lista ya no
# esta cableada en `block_range_valid`, sino en los parametros de la instancia.
# Lo comprueba x.tests/test_monitor_port.py.
# La configuración de warps está en 0x80001000 (segunda página, exclusiva de la
# GPU) y no en 0x80000000, que queda para periféricos compartidos con la CPU.
# Ver docs/resumen-prototipos.md.
SYSID_BASE = 0x8000_0000         # SYSTEM (mmio.md §5), siete palabras
WARP_CONFIG_BASE = 0x8201_0000   # GPU WARPS (§14.2), ocho descriptores
SIMT_DEBUG_BASE = 0x8202_0000    # GPU SIMT DEBUG (§14.3), cinco registros
GPU_PERF_BASE = 0x8203_0000      # GPU PERFORMANCE (§14.4)
MONITOR_REGIONS = (
    (SYSID_BASE, 0x8000_001c),
    (WARP_CONFIG_BASE, 0x8201_0080),
    (SIMT_DEBUG_BASE, 0x8202_0014),
    # Solo la ranura 1, RETIRED. Este prototipo no tiene contador de ciclos,
    # así que la ranura 0 no se abre: contestaría error.
    (GPU_PERF_BASE + 0x04, GPU_PERF_BASE + 0x08),
)
MEMORY_REGIONS = ARCHITECTURAL_REGIONS + MONITOR_REGIONS

# `tools` en el camino ANTES de importar de ahi. El insert ya existia
# mas abajo, para tools/serial_ports.py, pero ahora hace falta aqui
# arriba; es idempotente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# El protocolo del monitor vive UNA vez, en tools/monitor_protocol.py:
# veinte de los veintiun metodos de este cliente eran identicos en las
# diez carpetas con juego de comandos. Lo que se queda aqui es lo que
# describe a ESTE prototipo: su baudrate, su mapa y los comandos que su
# hardware tiene de verdad -- por eso los mixins se componen y no se
# heredan todos.
from tools import monitor_protocol as protocolo  # noqa: E402
from tools.monitor_protocol import (  # noqa: E402,F401
    MAX_BLOCK_SIZE,
    CpuStatus,
    MonitorError,
    Version,
    parse_integer,
    WarpMixin,
)

# El cuerpo de una clase no puede LEER un global que ademas asigna, asi
# que estos alias son lo que permite que el atributo de clase y la
# constante del modulo -que es la que se lee desde fuera- se llamen
# igual.
_REGIONES = MEMORY_REGIONS
_WARP_CONFIG_BASE = WARP_CONFIG_BASE
_SIMT_DEBUG_BASE = SIMT_DEBUG_BASE


class MonitorClient(WarpMixin, protocolo.MonitorClient):
    MEMORY_REGIONS = _REGIONES
    # `DEBUG_BASE` también hay que declararlo: el valor por defecto de
    # `WarpMixin` sigue siendo el de v1 (0x80000100) porque la 22 todavía no
    # está migrada. Sin esta línea, `select_context` escribiría en una
    # dirección que este bitstream rechaza, y el síntoma sería «registros del
    # warp equivocado», no un error.
    DEBUG_BASE = _SIMT_DEBUG_BASE
    WARP_CONFIG_BASE = _WARP_CONFIG_BASE
    # La memoria del MODELO con el que se valida el JSON antes de tocar la
    # placa. Es la de ESTE prototipo: un pc fuera de ella tiene que fallar
    # aqui y no despues, con los warps a medio escribir.
    MODEL_MEMORY_SIZE = 128 * 1024                # 128 KiB de EBR: esta carpeta no tiene SDRAM


def validate_block(address: int, length: int) -> None:
    protocolo.validate_block(address, length, MEMORY_REGIONS)


def validate_transfer(address: int, length: int) -> None:
    protocolo.validate_transfer(address, length, MEMORY_REGIONS)


# Deteccion del puerto y listado: en tools/serial_ports.py.
#
# Estaba COPIADA palabra por palabra en los trece monitores, y coger el primer
# puerto del sistema no vale: con la placa desenchufada ese primero puede ser
# el puerto serie de la placa base o un enlace Bluetooth, y entonces el fallo
# aparece tarde y disfrazado de timeout. Se filtra por fabricante (FTDI).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.serial_ports import (  # noqa: E402
    FTDI_VENDOR_ID,
    PortError,
    available_ports,
    detect_port,
    ftdi_ports,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Communicate with the minimal FPGA UART monitor."
    )
    parser.add_argument(
        "command",
        choices=(
            "ping",
            "get-version",
            "write-byte",
            "read-byte",
            "read-word",
            "write-word",
            "write-block",
            "read-block",
            "verify",
            "run",
            "halt",
            "step",
            "status",
            "read-register",
            "registers",
            "reset",
            "configure",
            "warp-status",
        ),
    )
    parser.add_argument("arguments", nargs="*", metavar="ARG")
    parser.add_argument("--warp", type=int, choices=range(8), default=0)
    parser.add_argument("--lane", type=int, choices=range(8), default=0)
    parser.add_argument(
        "--all",
        dest="all_contexts",
        action="store_true",
        help="With registers, show every warp/lane context",
    )
    parser.add_argument("--baudrate", type=int, default=BAUDRATE)
    parser.add_argument(
        "--port",
        default=None,
        help="Puerto serie de la ULX3S (por defecto: el unico FTDI conectado)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Response timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args()


def format_registers(warp: int, lane: int, registers: list[int]) -> str:
    """Format one lane compactly as four rows of eight hexadecimal registers."""
    if len(registers) != 32:
        raise ValueError("A GPU lane must have exactly 32 registers")
    lines = [f"warp={warp} lane={lane}"]
    for first in range(0, 32, 8):
        lines.append(
            "  " + "  ".join(
                f"R{register:02d}=0x{registers[register]:08x}"
                for register in range(first, first + 8)
            )
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()

    try:
        if args.all_contexts and args.command != "registers":
            raise MonitorError("--all is only valid with the registers command")
        expected_arguments = {
            "ping": 0,
            "get-version": 0,
            "write-byte": 2,
            "read-byte": 1,
            "read-word": 1,
            "write-word": 2,
            "write-block": 2,
            "read-block": 3,
            "verify": 2,
            "run": 0,
            "halt": 0,
            "step": 0,
            "status": 0,
            "read-register": 1,
            "registers": 0,
            "reset": 0,
            "configure": 1,
            "warp-status": 0,
        }
        if len(args.arguments) != expected_arguments[args.command]:
            raise MonitorError(
                f"{args.command} expects {expected_arguments[args.command]} argument(s)"
            )

        with serial.Serial(
            port=args.port if args.port is not None else detect_port(),
            baudrate=args.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=args.timeout,
            write_timeout=args.timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as connection:
            client = MonitorClient(connection)

            if args.command == "configure":
                config = json.loads(Path(args.arguments[0]).read_text(encoding='utf-8'))
                client.configure_warps(config)
                print("Warps configured, registers reset; use run to launch")
            elif args.command == "warp-status":
                for warp in range(8):
                    data = client.read_memory(WARP_CONFIG_BASE + warp * 16, 16)
                    pc, masks, group, state = (int.from_bytes(data[i:i+4], 'little') for i in range(0,16,4))
                    print(f"warp={warp} pc=0x{pc:08x} active=0x{masks & 255:02x} "
                          f"live=0x{masks >> 8 & 255:02x} group={group} "
                          f"regions={state & 255} paths={state >> 8 & 255} wait_mem={bool(state & 0x10000)} wait_bar={bool(state & 0x20000)}")
            elif args.command == "ping":
                client.ping()
                print("PONG: FPGA monitor is responding")
            elif args.command == "get-version":
                version = client.get_version()
                print(f"FPGA monitor version: {version}")
            elif args.command == "write-byte":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = parse_integer(args.arguments[1], 0xFF, "byte value")
                client.write_byte(address, value)
                print(f"Written 0x{value:02x} at address 0x{address:04x}")
            elif args.command == "read-byte":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = client.read_byte(address)
                print(f"Address 0x{address:04x}: 0x{value:02x}")
            elif args.command == "read-word":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = client.read_word(address)
                print(f"Address 0x{address:08x}: 0x{value:08x}")
            elif args.command == "write-word":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = parse_integer(args.arguments[1], 0xFFFF_FFFF, "word value")
                client.write_word(address, value)
                print(f"Written 0x{value:08x} at address 0x{address:08x}")
            elif args.command == "write-block":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                source = Path(args.arguments[1])
                data = source.read_bytes()
                client.write_memory(address, data)
                print(f"Written {len(data)} byte(s) at address 0x{address:04x}")
            elif args.command == "read-block":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                length = parse_integer(args.arguments[1], MAX_ADDRESS + 1, "length")
                destination = Path(args.arguments[2])
                data = client.read_memory(address, length)
                destination.write_bytes(data)
                print(
                    f"Read {len(data)} byte(s) from address 0x{address:04x} "
                    f"into {destination}"
                )
            elif args.command == "verify":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                source = Path(args.arguments[1])
                expected = source.read_bytes()
                actual = client.read_memory(address, len(expected))
                if actual != expected:
                    mismatch = next(
                        index
                        for index, (left, right) in enumerate(zip(actual, expected))
                        if left != right
                    )
                    raise MonitorError(
                        f"Verification failed at address 0x{address + mismatch:04x}: "
                        f"memory=0x{actual[mismatch]:02x}, file=0x{expected[mismatch]:02x}"
                    )
                print(f"Verified {len(expected)} byte(s) at address 0x{address:04x}")
            elif args.command == "run":
                client.run_cpu()
                print("GPU started")
            elif args.command == "halt":
                client.halt_cpu()
                print("GPU halt requested; poll status until halted")
            elif args.command == "step":
                client.step_cpu()
                print("GPU warp-instruction step requested")
            elif args.command == "status":
                status = client.get_status()
                if status.halted:
                    client.select_context(args.warp, args.lane)
                    status = client.get_status()
                print(
                    f"GPU halted={status.halted} error={status.error} "
                    f"error_code=0x{status.error_code:02x} pc=0x{status.pc:08x}"
                )
            elif args.command == "read-register":
                register = parse_integer(args.arguments[0], 31, "register number")
                client.select_context(args.warp, args.lane)
                value = client.read_register(register)
                print(f"warp={args.warp} lane={args.lane} R{register} = 0x{value:08x} ({value})")
            elif args.command == "registers":
                if not client.get_status().halted:
                    raise MonitorError("Halt the GPU before reading registers")
                contexts = (
                    ((warp, lane) for warp in range(8) for lane in range(8))
                    if args.all_contexts
                    else ((args.warp, args.lane),)
                )
                print("\n\n".join(
                    format_registers(warp, lane, client.read_registers(warp, lane))
                    for warp, lane in contexts
                ))
            else:
                client.reset_cpu()
                print("GPU reset: eight full warps at PC=0; memory preserved")

    except (MonitorError, PortError, OSError, ValueError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
