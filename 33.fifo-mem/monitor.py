#!/usr/bin/env python3
"""Cliente UART del banco de pruebas FIFO/fabric/SDRAM."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import serial


BAUDRATE = 250_000
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0xFFFF_FFFF

# Memoria SDRAM y ventana de diagnostico que acepta la instancia de monitor.v
# en top_bl8.v. Los limites superiores son exclusivos.
SDRAM_REGION = (0x0000_0000, 0x0200_0000)
MEMTEST_REGION = (0x8120_0000, 0x8121_0000)
MEMORY_REGIONS = (SDRAM_REGION, MEMTEST_REGION)


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import monitor_protocol as protocolo  # noqa: E402
from tools.monitor_protocol import MonitorError, parse_integer  # noqa: E402
from tools.serial_ports import (  # noqa: E402
    PortError,
    available_ports,
    detect_port,
)


class MonitorClient(protocolo.MonitorClient):
    MEMORY_REGIONS = MEMORY_REGIONS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comunica con el monitor UART del banco FIFO/fabric/SDRAM."
    )
    parser.add_argument(
        "command",
        choices=(
            "ping",
            "get-version",
            "write-byte",
            "read-byte",
            "write-word",
            "read-word",
            "write-block",
            "read-block",
            "verify",
        ),
    )
    parser.add_argument("arguments", nargs="*", metavar="ARG")
    parser.add_argument("--baudrate", type=int, default=BAUDRATE)
    parser.add_argument(
        "--port",
        default=None,
        help="Puerto serie de la ULX3S (por defecto: el unico FTDI conectado)",
    )
    parser.add_argument(
        "--serial-timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout de respuesta en segundos (por defecto: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        expected_arguments = {
            "ping": 0,
            "get-version": 0,
            "write-byte": 2,
            "read-byte": 1,
            "write-word": 2,
            "read-word": 1,
            "write-block": 2,
            "read-block": 3,
            "verify": 2,
        }
        expected = expected_arguments[args.command]
        if len(args.arguments) != expected:
            raise MonitorError(f"{args.command} expects {expected} argument(s)")

        with serial.Serial(
            port=args.port if args.port is not None else detect_port(),
            baudrate=args.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=args.serial_timeout,
            write_timeout=args.serial_timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as connection:
            client = MonitorClient(connection)

            if args.command == "ping":
                client.ping()
                print("PONG: FPGA monitor is responding")
            elif args.command == "get-version":
                print(f"FPGA monitor version: {client.get_version()}")
            elif args.command == "write-byte":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = parse_integer(args.arguments[1], 0xFF, "byte value")
                client.write_byte(address, value)
                print(f"Written 0x{value:02x} at address 0x{address:08x}")
            elif args.command == "read-byte":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = client.read_byte(address)
                print(f"Address 0x{address:08x}: 0x{value:02x}")
            elif args.command == "write-word":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = parse_integer(args.arguments[1], 0xFFFF_FFFF, "word value")
                client.write_word(address, value)
                print(f"Written 0x{value:08x} at address 0x{address:08x}")
            elif args.command == "read-word":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = client.read_word(address)
                print(f"Address 0x{address:08x}: 0x{value:08x}")
            elif args.command == "write-block":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                source = Path(args.arguments[1])
                data = source.read_bytes()
                client.write_memory(address, data)
                print(f"Written {len(data)} byte(s) at address 0x{address:08x}")
            elif args.command == "read-block":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                length = parse_integer(args.arguments[1], MAX_ADDRESS + 1, "length")
                destination = Path(args.arguments[2])
                data = client.read_memory(address, length)
                destination.write_bytes(data)
                print(
                    f"Read {len(data)} byte(s) from address 0x{address:08x} "
                    f"into {destination}"
                )
            else:
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                source = Path(args.arguments[1])
                expected_data = source.read_bytes()
                actual = client.read_memory(address, len(expected_data))
                if actual != expected_data:
                    mismatch = next(
                        index
                        for index, (actual_byte, expected_byte) in enumerate(
                            zip(actual, expected_data)
                        )
                        if actual_byte != expected_byte
                    )
                    raise MonitorError(
                        f"Verification failed at address 0x{address + mismatch:08x}: "
                        f"memory=0x{actual[mismatch]:02x}, "
                        f"file=0x{expected_data[mismatch]:02x}"
                    )
                print(
                    f"Verified {len(expected_data)} byte(s) "
                    f"at address 0x{address:08x}"
                )

    except (MonitorError, PortError, OSError, ValueError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
