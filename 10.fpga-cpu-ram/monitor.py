#!/usr/bin/env python3
"""Command-line client for the minimal FPGA UART monitor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import serial

# 1 Mbaud, no 3: el reloj bajo a 100 MHz y 100/100 = 1 Mbaud exacto, el mismo
# que 16, 18, 19 y 21. A 100 MHz no hay divisor que de 3 Mbaud (33,33), `uart.v`
# ademas exige multiplo de 4 --sobremuestrea a x4-- y 2,5 Mbaud no lo sabe hacer
# el FTDI. Gemelo de `UART_CLOCKS_PER_BIT` en `top.v`.
BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0x01FF_FFFF
# Espacio físico unificado: la CPU y el monitor ven las mismas direcciones.
ARCHITECTURAL_REGIONS = (
    (0x0000_0000, 0x0200_0000),
)
# La 10 no tiene periféricos mapeados, pero sí `sysid`: cuatro palabras de solo
# lectura en el camino del monitor, que es lo que le permite decir quién es sin
# tener ventana MMIO de verdad. Ver docs/unificacion-mmio.md fase 4a.
#
# Hay que declararlo aquí aunque `read_word` no valide: `read_memory` y
# `read_block` sí, así que sin esta línea leer la identificación por bloque se
# rechazaría en el host antes de llegar al cable. Gemela de las ventanas que
# top.v pasa al monitor.
SYSID_BASE = 0x8000_0f00
MONITOR_REGIONS = (
    (SYSID_BASE, 0x8000_0f10),   # identificación: SYS_ID, CONTRACT…
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
)

# El cuerpo de una clase no puede LEER un global que ademas asigna, asi
# que estos alias son lo que permite que el atributo de clase y la
# constante del modulo -que es la que se lee desde fuera- se llamen
# igual.
_REGIONES = MEMORY_REGIONS


class MonitorClient(protocolo.MonitorClient):
    MEMORY_REGIONS = _REGIONES


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
            "memory-test",
            "run",
            "halt",
            "step",
            "status",
            "read-register",
            "reset",
        ),
    )
    parser.add_argument("arguments", nargs="*", metavar="ARG")
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


def test_pattern(number: int, address: int, length: int) -> bytes:
    """Build one deterministic SDRAM test pattern for a physical byte range."""
    if number == 0:
        return bytes(length)
    if number == 1:
        return bytes((0xFF,)) * length
    if number == 2:
        return bytes(((address + offset) ^ 0xA5) & 0xFF for offset in range(length))
    return bytes(0xAA if (address + offset) & 1 else 0x55 for offset in range(length))


def memory_test(client: MonitorClient, address: int, length: int) -> None:
    """Destructively write and verify four patterns over an SDRAM range."""
    validate_transfer(address, length)
    names = ("00", "ff", "address XOR a5", "55/aa")
    for pattern_number, name in enumerate(names):
        print(f"Pattern {pattern_number + 1}/4: {name} (write)", flush=True)
        for offset in range(0, length, MAX_BLOCK_SIZE):
            size = min(MAX_BLOCK_SIZE, length - offset)
            client.write_block(
                address + offset,
                test_pattern(pattern_number, address + offset, size),
            )

        print(f"Pattern {pattern_number + 1}/4: {name} (verify)", flush=True)
        for offset in range(0, length, MAX_BLOCK_SIZE):
            size = min(MAX_BLOCK_SIZE, length - offset)
            expected = test_pattern(pattern_number, address + offset, size)
            actual = client.read_block(address + offset, size)
            if actual != expected:
                mismatch = next(
                    index
                    for index, (left, right) in enumerate(zip(actual, expected))
                    if left != right
                )
                absolute = address + offset + mismatch
                raise MonitorError(
                    f"Memory test failed at 0x{absolute:08x}: "
                    f"memory=0x{actual[mismatch]:02x}, "
                    f"expected=0x{expected[mismatch]:02x}"
                )

    print(f"SDRAM test passed: {length} byte(s) from 0x{address:08x}")


def main() -> int:
    args = parse_args()

    try:
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
            "memory-test": 2,
            "run": 0,
            "halt": 0,
            "step": 0,
            "status": 0,
            "read-register": 1,
            "reset": 0,
        }
        if len(args.arguments) != expected_arguments[args.command]:
            raise MonitorError(
                f"{args.command} expects {expected_arguments[args.command]} argument(s)"
            )

        with serial.Serial(
            port=args.port if args.port is not None else detect_port(),
            baudrate=BAUDRATE,
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

            if args.command == "ping":
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
            elif args.command == "memory-test":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                length = parse_integer(args.arguments[1], MAX_ADDRESS + 1, "length")
                memory_test(client, address, length)
            elif args.command == "run":
                client.run_cpu()
                print("CPU started")
            elif args.command == "halt":
                client.halt_cpu()
                print("CPU halt requested")
            elif args.command == "step":
                client.step_cpu()
                print("CPU step requested")
            elif args.command == "status":
                status = client.get_status()
                print(
                    f"CPU halted={status.halted} error={status.error} "
                    f"error_code=0x{status.error_code:02x} pc=0x{status.pc:08x}"
                )
            elif args.command == "read-register":
                register = parse_integer(args.arguments[0], 31, "register number")
                value = client.read_register(register)
                print(f"R{register} = 0x{value:08x} ({value})")
            else:
                client.reset_cpu()
                print("CPU reset: PC, registers and error state cleared")

    except (MonitorError, PortError, OSError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
