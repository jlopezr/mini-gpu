#!/usr/bin/env python3
"""Command-line client for the minimal FPGA UART monitor."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import serial
from serial.tools import list_ports

BAUDRATE = 3_000_000
DEFAULT_TIMEOUT = 1.0

CMD_PING = b"\x01"
CMD_GET_VERSION = b"\x02"

RSP_PONG = b"\x81"
RSP_VERSION = 0x82
RSP_ERROR = 0xFF


class MonitorError(Exception):
    """Raised when communication with the FPGA monitor fails."""


@dataclass(frozen=True)
class Version:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


class MonitorClient:
    def __init__(self, connection: serial.Serial) -> None:
        self.connection = connection

    def _request(self, command: bytes, response_size: int) -> bytes:
        self.connection.reset_input_buffer()
        self.connection.write(command)
        self.connection.flush()

        response = self.connection.read(response_size)
        if len(response) != response_size:
            raise MonitorError(
                f"Timeout: expected {response_size} response byte(s), "
                f"received {len(response)}"
            )
        if response[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")

        return response

    def ping(self) -> None:
        response = self._request(CMD_PING, len(RSP_PONG))
        if response != RSP_PONG:
            raise MonitorError(f"Invalid PING response: {response.hex(' ')}")

    def get_version(self) -> Version:
        response = self._request(CMD_GET_VERSION, 3)
        if response[0] != RSP_VERSION:
            raise MonitorError(f"Invalid GET_VERSION response: {response.hex(' ')}")

        return Version(major=response[1], minor=response[2])


def available_ports() -> str:
    ports = list(list_ports.comports())
    if not ports:
        return "No serial ports detected"

    return "Available ports: " + ", ".join(port.device for port in ports)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Communicate with the minimal FPGA UART monitor."
    )
    parser.add_argument("command", choices=("ping", "get-version"))
    parser.add_argument(
        "--port",
        default="COM3",
        help="Serial port connected to the ULX3S (default: COM3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Response timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        with serial.Serial(
            port=args.port,
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
            else:
                version = client.get_version()
                print(f"FPGA monitor version: {version}")

    except (MonitorError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
