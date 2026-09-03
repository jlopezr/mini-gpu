#!/usr/bin/env python3
"""Command-line client for the minimal FPGA UART monitor."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import serial
from serial.tools import list_ports

def read_verilog_integer(name: str) -> int:
    """Read a decimal localparam from top.v, accepting '_' separators."""
    source = Path(__file__).with_name("top.v").read_text(encoding="utf-8")
    match = re.search(
        rf"localparam\s+integer\s+{re.escape(name)}\s*=\s*([0-9_]+)\s*;",
        source,
    )
    if match is None:
        raise RuntimeError(f"Cannot find {name} in top.v")
    return int(match.group(1).replace("_", ""))


def uart_settings(clock_hz: int) -> tuple[int, int]:
    """Mirror top.v's integer, x4-compatible UART divisor calculation."""
    if clock_hz // UART_CLOCKS_PER_BIT <= UART_MAX_BAUD:
        divisor = UART_CLOCKS_PER_BIT
    else:
        minimum_divisor = (clock_hz + UART_MAX_BAUD - 1) // UART_MAX_BAUD
        divisor = ((minimum_divisor + 3) // 4) * 4
    return divisor, round(clock_hz / divisor)


CLK_FREQ_HZ = read_verilog_integer("CLK_FREQ_HZ")
UART_CLOCKS_PER_BIT = read_verilog_integer("UART_CLOCKS_PER_BIT")
UART_MAX_BAUD = read_verilog_integer("UART_MAX_BAUD")
UART_DIVISOR, BAUDRATE = uart_settings(CLK_FREQ_HZ)
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0x01FF_FFFF
MAX_BLOCK_SIZE = 256

CMD_PING = b"\x01"
CMD_GET_VERSION = b"\x02"
CMD_WRITE_BYTE = 0x10
CMD_READ_BYTE = 0x11
CMD_WRITE_BLOCK = 0x20
CMD_READ_BLOCK = 0x21

RSP_PONG = b"\x81"
RSP_VERSION = 0x82
RSP_WRITE_BYTE = b"\x90"
RSP_READ_BYTE = 0x91
RSP_WRITE_BLOCK = b"\xa0"
RSP_READ_BLOCK = 0xA1
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

    def write_byte(self, address: int, value: int) -> None:
        request = bytes((CMD_WRITE_BYTE,)) + address.to_bytes(4, "big") + bytes((value,))
        response = self._request(request, len(RSP_WRITE_BYTE))
        if response != RSP_WRITE_BYTE:
            raise MonitorError(f"Invalid WRITE_BYTE response: {response.hex(' ')}")

    def read_byte(self, address: int) -> int:
        request = bytes((CMD_READ_BYTE,)) + address.to_bytes(4, "big")
        response = self._request(request, 2)
        if response[0] != RSP_READ_BYTE:
            raise MonitorError(f"Invalid READ_BYTE response: {response.hex(' ')}")

        return response[1]

    def write_block(self, address: int, data: bytes) -> None:
        validate_block(address, len(data))
        request = (
            bytes((CMD_WRITE_BLOCK,))
            + address.to_bytes(4, "big")
            + len(data).to_bytes(2, "big")
            + data
        )
        response = self._request(request, len(RSP_WRITE_BLOCK))
        if response != RSP_WRITE_BLOCK:
            raise MonitorError(f"Invalid WRITE_BLOCK response: {response.hex(' ')}")

    def read_block(self, address: int, length: int) -> bytes:
        validate_block(address, length)
        request = (
            bytes((CMD_READ_BLOCK,))
            + address.to_bytes(4, "big")
            + length.to_bytes(2, "big")
        )
        response = self._request(request, length + 1)
        if response[0] != RSP_READ_BLOCK:
            raise MonitorError(f"Invalid READ_BLOCK response: {response.hex(' ')}")

        return response[1:]

    def write_memory(self, address: int, data: bytes) -> None:
        validate_transfer(address, len(data))
        for offset in range(0, len(data), MAX_BLOCK_SIZE):
            chunk = data[offset : offset + MAX_BLOCK_SIZE]
            self.write_block(address + offset, chunk)

    def read_memory(self, address: int, length: int) -> bytes:
        validate_transfer(address, length)
        result = bytearray()
        for offset in range(0, length, MAX_BLOCK_SIZE):
            chunk_length = min(MAX_BLOCK_SIZE, length - offset)
            result.extend(self.read_block(address + offset, chunk_length))
        return bytes(result)


def available_ports() -> str:
    ports = list(list_ports.comports())
    if not ports:
        return "No serial ports detected"

    return "Available ports: " + ", ".join(port.device for port in ports)


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
            "write-block",
            "read-block",
            "verify",
            "memory-test",
        ),
    )
    parser.add_argument("arguments", nargs="*", metavar="ARG")
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


def parse_integer(value: str, maximum: int, description: str) -> int:
    try:
        result = int(value, 0)
    except ValueError as error:
        raise MonitorError(f"Invalid {description}: {value}") from error

    if not 0 <= result <= maximum:
        raise MonitorError(
            f"{description.capitalize()} must be between 0 and 0x{maximum:x}"
        )
    return result


def validate_block(address: int, length: int) -> None:
    if not 1 <= length <= MAX_BLOCK_SIZE:
        raise MonitorError(f"Block length must be between 1 and {MAX_BLOCK_SIZE}")
    if address + length > MAX_ADDRESS + 1:
        raise MonitorError("Block crosses the end of monitor memory")


def validate_transfer(address: int, length: int) -> None:
    if length < 1:
        raise MonitorError("Transfer must contain at least one byte")
    if address + length > MAX_ADDRESS + 1:
        raise MonitorError("Transfer crosses the end of monitor memory")


def test_pattern(number: int, address: int, length: int) -> bytes:
    if number == 0:
        return bytes(length)
    if number == 1:
        return bytes((0xFF,)) * length
    if number == 2:
        return bytes(((address + offset) ^ 0xA5) & 0xFF for offset in range(length))
    return bytes(0xAA if (address + offset) & 1 else 0x55 for offset in range(length))


def memory_test(client: MonitorClient, address: int, length: int) -> None:
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
                mismatch = next(i for i, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1])
                absolute = address + offset + mismatch
                raise MonitorError(
                    f"Memory test failed at 0x{absolute:08x}: "
                    f"memory=0x{actual[mismatch]:02x}, expected=0x{expected[mismatch]:02x}"
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
            "write-block": 2,
            "read-block": 3,
            "verify": 2,
            "memory-test": 2,
        }
        if len(args.arguments) != expected_arguments[args.command]:
            raise MonitorError(
                f"{args.command} expects {expected_arguments[args.command]} argument(s)"
            )

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
            elif args.command == "get-version":
                version = client.get_version()
                print(f"FPGA monitor version: {version}")
            elif args.command == "write-byte":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = parse_integer(args.arguments[1], 0xFF, "byte value")
                client.write_byte(address, value)
                print(f"Written 0x{value:02x} at address 0x{address:08x}")
            elif args.command == "read-byte":
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                value = client.read_byte(address)
                print(f"Address 0x{address:08x}: 0x{value:02x}")
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
                        f"Verification failed at address 0x{address + mismatch:08x}: "
                        f"memory=0x{actual[mismatch]:02x}, file=0x{expected[mismatch]:02x}"
                    )
                print(f"Verified {len(expected)} byte(s) at address 0x{address:08x}")
            else:
                address = parse_integer(args.arguments[0], MAX_ADDRESS, "address")
                length = parse_integer(args.arguments[1], MAX_ADDRESS + 1, "length")
                memory_test(client, address, length)

    except (MonitorError, OSError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
