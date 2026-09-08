#!/usr/bin/env python3
"""MiniGPU UART client: unified RAM, warp launch configuration and lane debug."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import serial
from serial.tools import list_ports

BAUDRATE = 250_000
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0xFFFF_FFFF
MAX_BLOCK_SIZE = 256
MEMORY_REGIONS = (
    (0x0000_0000, 0x0002_0000),
    (0x8000_0000, 0x8000_0080),
    (0x8000_0100, 0x8000_0114),
)

CMD_PING = b"\x01"
CMD_GET_VERSION = b"\x02"
CMD_WRITE_BYTE = 0x10
CMD_READ_BYTE = 0x11
CMD_WRITE_BLOCK = 0x20
CMD_READ_BLOCK = 0x21
CMD_RUN = 0x30
CMD_HALT = 0x31
CMD_STEP = 0x32
CMD_GET_STATUS = 0x33
CMD_READ_REGISTER = 0x34
CMD_RESET_CPU = 0x35

RSP_PONG = b"\x81"
RSP_VERSION = 0x82
RSP_WRITE_BYTE = b"\x90"
RSP_READ_BYTE = 0x91
RSP_WRITE_BLOCK = b"\xa0"
RSP_READ_BLOCK = 0xA1
RSP_RUN = b"\xb0"
RSP_HALT = b"\xb1"
RSP_STEP = b"\xb2"
RSP_STATUS = 0xB3
RSP_READ_REGISTER = 0xB4
RSP_RESET_CPU = b"\xb5"
RSP_ERROR = 0xFF


class MonitorError(Exception):
    """Raised when communication with the FPGA monitor fails."""


@dataclass(frozen=True)
class Version:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True)
class CpuStatus:
    halted: bool
    error: bool
    error_code: int
    pc: int


class MonitorClient:
    def __init__(self, connection: serial.Serial) -> None:
        self.connection = connection

    def select_context(self, warp: int, lane: int) -> None:
        if not 0 <= warp < 8 or not 0 <= lane < 8:
            raise MonitorError("Warp and lane must be in 0..7")
        self.write_byte(0x80000100, warp * 8 + lane)

    def configure_warps(self, config: object) -> None:
        # Share JSON validation with the simulator, before modifying hardware.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '11.gpu-sim-func'))
        from minigpu_sim import System
        model = System(128 * 1024, 8, 8)
        try:
            model.configure_warps(config)
        except (ValueError, TypeError) as exc:
            raise MonitorError(str(exc)) from exc
        warps = model.streaming_multiprocessor.warps
        if any(w.workgroup_id > 0xffffffff for w in warps):
            raise MonitorError("Hardware workgroup IDs must fit in 32 bits")
        if not self.get_status().halted:
            raise MonitorError("Halt the GPU before configuring warps")
        self.reset_cpu()
        deadline = time.monotonic() + 2
        while not self.get_status().halted:
            if time.monotonic() > deadline:
                raise MonitorError("GPU did not finish register initialization")
        for w in warps:
            base = 0x80000000 + w.warp_id * 16
            self.write_memory(base, w.pc.to_bytes(4, 'little'))
            self.write_memory(base + 4, w.active_mask.to_bytes(4, 'little'))
            self.write_memory(base + 8, w.workgroup_id.to_bytes(4, 'little'))

    def _send(self, command: bytes) -> None:
        self.connection.reset_input_buffer()
        self.connection.write(command)
        self.connection.flush()

    def _read_exact(self, response_size: int) -> bytes:
        response = self.connection.read(response_size)
        if len(response) != response_size:
            raise MonitorError(
                f"Timeout: expected {response_size} response byte(s), "
                f"received {len(response)}"
            )
        return response

    def _request(self, command: bytes, response_size: int) -> bytes:
        self._send(command)
        response = self._read_exact(response_size)
        if response[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        return response

    @staticmethod
    def _address_bytes(address: int) -> bytes:
        return address.to_bytes(4, byteorder="big")

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
        request = bytes((CMD_WRITE_BYTE,)) + self._address_bytes(address) + bytes((value,))
        response = self._request(request, len(RSP_WRITE_BYTE))
        if response != RSP_WRITE_BYTE:
            raise MonitorError(f"Invalid WRITE_BYTE response: {response.hex(' ')}")

    def read_byte(self, address: int) -> int:
        request = bytes((CMD_READ_BYTE,)) + self._address_bytes(address)
        self._send(request)
        header = self._read_exact(1)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_READ_BYTE:
            raise MonitorError(f"Invalid READ_BYTE response: {header.hex(' ')}")

        return self._read_exact(1)[0]

    def write_block(self, address: int, data: bytes) -> None:
        validate_block(address, len(data))
        request = (
            bytes((CMD_WRITE_BLOCK,))
            + self._address_bytes(address)
            + len(data).to_bytes(2, byteorder="big")
            + data
        )
        response = self._request(request, len(RSP_WRITE_BLOCK))
        if response != RSP_WRITE_BLOCK:
            raise MonitorError(f"Invalid WRITE_BLOCK response: {response.hex(' ')}")

    def read_block(self, address: int, length: int) -> bytes:
        validate_block(address, length)
        request = (
            bytes((CMD_READ_BLOCK,))
            + self._address_bytes(address)
            + length.to_bytes(2, byteorder="big")
        )
        self._send(request)
        header = self._read_exact(1)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_READ_BLOCK:
            raise MonitorError(f"Invalid READ_BLOCK response: {header.hex(' ')}")

        return self._read_exact(length)

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

    def run_cpu(self) -> None:
        response = self._request(bytes((CMD_RUN,)), 1)
        if response != RSP_RUN:
            raise MonitorError(f"Invalid RUN response: {response.hex(' ')}")

    def halt_cpu(self) -> None:
        response = self._request(bytes((CMD_HALT,)), 1)
        if response != RSP_HALT:
            raise MonitorError(f"Invalid HALT response: {response.hex(' ')}")

    def step_cpu(self) -> None:
        response = self._request(bytes((CMD_STEP,)), 1)
        if response != RSP_STEP:
            raise MonitorError(f"Invalid STEP response: {response.hex(' ')}")

    def get_status(self) -> CpuStatus:
        response = self._request(bytes((CMD_GET_STATUS,)), 7)
        if response[0] != RSP_STATUS:
            raise MonitorError(f"Invalid STATUS response: {response.hex(' ')}")

        return CpuStatus(
            halted=bool(response[1] & 0x01),
            error=bool(response[1] & 0x02),
            error_code=response[2],
            pc=int.from_bytes(response[3:7], byteorder="big"),
        )

    def read_register(self, register: int) -> int:
        if not 0 <= register < 32:
            raise MonitorError("Register number must be between 0 and 31")

        self._send(bytes((CMD_READ_REGISTER, register)))
        header = self._read_exact(1)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_READ_REGISTER:
            raise MonitorError(f"Invalid READ_REG response: {header.hex(' ')}")
        return int.from_bytes(self._read_exact(4), byteorder="big")

    def reset_cpu(self) -> None:
        response = self._request(bytes((CMD_RESET_CPU,)), 1)
        if response != RSP_RESET_CPU:
            raise MonitorError(f"Invalid RESET_CPU response: {response.hex(' ')}")


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
            "run",
            "halt",
            "step",
            "status",
            "read-register",
            "reset",
            "configure",
            "warp-status",
        ),
    )
    parser.add_argument("arguments", nargs="*", metavar="ARG")
    parser.add_argument("--warp", type=int, choices=range(8), default=0)
    parser.add_argument("--lane", type=int, choices=range(8), default=0)
    parser.add_argument("--baudrate", type=int, default=BAUDRATE)
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
    if not any(start <= address and address + length <= end for start, end in MEMORY_REGIONS):
        raise MonitorError("Block is outside the currently implemented memory regions")


def validate_transfer(address: int, length: int) -> None:
    if length < 1:
        raise MonitorError("Transfer must contain at least one byte")
    if not any(start <= address and address + length <= end for start, end in MEMORY_REGIONS):
        raise MonitorError("Transfer is outside the currently implemented memory regions")


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
            "run": 0,
            "halt": 0,
            "step": 0,
            "status": 0,
            "read-register": 1,
            "reset": 0,
            "configure": 1,
            "warp-status": 0,
        }
        if len(args.arguments) != expected_arguments[args.command]:
            raise MonitorError(
                f"{args.command} expects {expected_arguments[args.command]} argument(s)"
            )

        with serial.Serial(
            port=args.port,
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
                    data = client.read_memory(0x80000000 + warp * 16, 16)
                    pc, masks, group, state = (int.from_bytes(data[i:i+4], 'little') for i in range(0,16,4))
                    print(f"warp={warp} pc=0x{pc:08x} active=0x{masks & 255:02x} "
                          f"live=0x{masks >> 8 & 255:02x} group={group} "
                          f"stack={state & 255} wait_mem={bool(state & 0x10000)} wait_bar={bool(state & 0x20000)}")
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
            else:
                client.reset_cpu()
                print("GPU reset: eight full warps at PC=0; memory preserved")

    except (MonitorError, OSError, ValueError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
