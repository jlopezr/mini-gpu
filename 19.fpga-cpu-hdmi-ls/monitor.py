#!/usr/bin/env python3
"""Command-line client for the minimal FPGA UART monitor."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import serial

# 1 Mbaud: el dominio de CPU corre a 100 MHz y el divisor es 100. Ese divisor
# es múltiplo de 4, que es lo que necesita la recepción de `uart.v` (muestrea
# a 4x con DIVISOR/4, y la división es entera), y 1 Mbaud es además 3 MHz / 3,
# que el generador del FTDI produce exacto. Ver el comentario de `top.v`.
BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0x01FF_FFFF
# Ventana MMIO: 4 KiB repartidos en dieciseis dispositivos de 256 bytes.
#
#   0x80000000  dispositivo 0, video
#   0x80000100  dispositivo 1, reservado a depuracion (lo usa la MiniGPU)
#   0x80000200  dispositivo 2, puerto serie
#
# Era de 32 bytes --solo el video-- hasta que entro el serie. El mapa completo
# esta en mmio_decoder.v.
MMIO_BASE = 0x8000_0000
MMIO_LIMIT = 0x8000_0FFF
SERIAL_BASE = 0x8000_0200
MAX_BLOCK_SIZE = 256
# Espacio físico unificado: la CPU y el monitor ven las mismas direcciones.
ARCHITECTURAL_REGIONS = (
    (0x0000_0000, 0x0200_0000),
)
MONITOR_REGIONS = ()
MEMORY_REGIONS = ARCHITECTURAL_REGIONS + MONITOR_REGIONS

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
CMD_GET_CYCLES = 0x36
CMD_GET_INSTRUCTIONS = 0x37
CMD_SEND_BYTES = 0x38
CMD_RECV_BYTES = 0x39

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
RSP_CYCLES = 0xB6
RSP_INSTRUCTIONS = 0xB7
RSP_SEND_BYTES = 0xB8
RSP_RECV_BYTES = 0xB9
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

    # ----------------------------------------------------------------- serie
    #
    # El puerto serie de la CPU viaja encapsulado en este mismo enlace, no por
    # un cable aparte. Estos dos metodos son el CODEC: convierten bytes en
    # paquetes y nada mas. El terminal interactivo vive fuera, en
    # `interactive_console()`, y esa separacion es lo que permite probar el
    # codec sin consola y sin placa.

    def send_bytes(self, data: bytes) -> int:
        """Mete lo que quepa en la cola de entrada y dice cuantos entraron.

        El valor devuelto puede ser MENOR que `len(data)`, y no es un error: es
        el control de flujo. La cola de la FPGA tiene 64 bytes y quien decide
        cuantos caben es ella. Ver `send_all()` para el bucle de reenvio.
        """
        if not 0 <= len(data) <= 255:
            raise ValueError("un paquete SEND_BYTES son entre 0 y 255 bytes")
        request = bytes((CMD_SEND_BYTES, len(data))) + data
        response = self._request(request, 2)
        if response[0] != RSP_SEND_BYTES:
            raise MonitorError(f"Invalid SEND_BYTES response: {response.hex(' ')}")
        accepted = response[1]
        if accepted > len(data):
            raise MonitorError(
                f"SEND_BYTES acepto {accepted} de {len(data)} bytes")
        return accepted

    def send_all(self, data: bytes, timeout: float = 5.0) -> None:
        """Reenvia hasta colocarlo todo, respetando el control de flujo."""
        pending = memoryview(data)
        deadline = time.monotonic() + timeout
        while pending:
            accepted = self.send_bytes(bytes(pending[:255]))
            pending = pending[accepted:]
            if accepted == 0:
                # La CPU no esta consumiendo. Sin este limite, un programa
                # parado deja al PC girando para siempre.
                if time.monotonic() >= deadline:
                    raise MonitorError(
                        f"la cola de entrada sigue llena tras {timeout:g} s; "
                        f"quedan {len(pending)} bytes. ¿Esta corriendo la CPU?")
                time.sleep(0.005)
            else:
                deadline = time.monotonic() + timeout

    def recv_bytes(self, maximum: int = 255) -> bytes:
        """Saca hasta `maximum` bytes de la cola de salida; puede devolver b''."""
        if not 1 <= maximum <= 255:
            raise ValueError("RECV_BYTES admite entre 1 y 255 bytes")
        self._send(bytes((CMD_RECV_BYTES, maximum)))
        header = self._read_exact(2)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_RECV_BYTES:
            raise MonitorError(f"Invalid RECV_BYTES response: {header.hex(' ')}")
        count = header[1]
        if count > maximum:
            raise MonitorError(f"RECV_BYTES devolvio {count} de {maximum}")
        return self._read_exact(count) if count else b""

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

    def _read_counter(self, command: int, expected: int, name: str) -> int:
        response = self._request(bytes((command,)), 5)
        if response[0] != expected:
            raise MonitorError(f"Invalid {name} response: {response.hex(' ')}")
        return int.from_bytes(response[1:5], byteorder="big")

    def get_cycles(self) -> int:
        """Ciclos que la CPU ha estado corriendo desde el ultimo RUN.

        Son dos comandos y no uno porque la respuesta del monitor cabe en 7
        bytes y los dos contadores juntos necesitan 9. Leerlos por separado
        significa que no son del mismo instante, pero se leen con la CPU ya
        parada, asi que ninguno de los dos se mueve entre una lectura y otra.
        """
        return self._read_counter(CMD_GET_CYCLES, RSP_CYCLES, "GET_CYCLES")

    def get_instructions(self) -> int:
        return self._read_counter(
            CMD_GET_INSTRUCTIONS, RSP_INSTRUCTIONS, "GET_INSTRUCTIONS")

    def reset_cpu(self) -> None:
        response = self._request(bytes((CMD_RESET_CPU,)), 1)
        if response != RSP_RESET_CPU:
            raise MonitorError(f"Invalid RESET_CPU response: {response.hex(' ')}")


def interactive_console(client: MonitorClient, poll: float = 0.005) -> None:
    """Terminal sobre el puerto serie de la CPU. Se sale con Ctrl+].

    Esto NO es el codec: es la parte que no se puede probar sin una persona
    delante. Todo lo que sí se puede probar --empaquetar, control de flujo,
    reensamblar-- vive en `send_bytes`/`recv_bytes`/`send_all`, que no saben
    nada de teclados. Por eso estan separados.

    La lectura de teclado usa `msvcrt`, no `select()`: esto es Windows. En otros
    sistemas cae a una lectura por lineas, que sirve para probar aunque no de
    caracter a caracter.
    """
    try:
        import msvcrt
    except ImportError:
        msvcrt = None

    print("Consola sobre el puerto serie de la CPU. Ctrl+] para salir.")
    if msvcrt is None:
        print("  (sin msvcrt: se envia por lineas, no caracter a caracter)")

    salida = sys.stdout
    while True:
        # Primero lo que venga de la placa, para que el eco se vea antes de
        # que el usuario escriba lo siguiente.
        datos = client.recv_bytes(255)
        if datos:
            salida.write(datos.decode("latin-1"))
            salida.flush()

        if msvcrt is not None:
            enviados = bytearray()
            while msvcrt.kbhit():
                tecla = msvcrt.getwch()
                if tecla == "\x1d":       # Ctrl+]
                    print()
                    return
                # Enter llega como \r y casi todo programa espera \n.
                enviados += ("\n" if tecla == "\r" else tecla).encode("latin-1")
            if enviados:
                client.send_all(bytes(enviados))
            elif not datos:
                time.sleep(poll)
        else:
            linea = sys.stdin.readline()
            if not linea:
                return
            client.send_all(linea.encode("latin-1"))


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
            "perf",
            "console",
            "send",
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


def parse_byte_address(value: str) -> int:
    """Dirección para acceso por bytes: SDRAM o la ventana de registros.

    Los registros de vídeo viven en `MMIO_BASE` y no son memoria, así que solo
    tienen sentido byte a byte: `write-block` y compañía siguen limitados a la
    SDRAM. Al contrario que la memoria, estos registros responden también con
    la CPU en marcha, que es lo que permite leer el contador de frames o mover
    el framebuffer mientras un programa dibuja.
    """
    try:
        result = int(value, 0)
    except ValueError as error:
        raise MonitorError(f"Invalid address: {value}") from error

    if 0 <= result <= MAX_ADDRESS or MMIO_BASE <= result <= MMIO_LIMIT:
        return result

    raise MonitorError(
        f"Address must be between 0 and 0x{MAX_ADDRESS:x}, "
        f"or inside the video register window "
        f"0x{MMIO_BASE:08x}-0x{MMIO_LIMIT:08x}"
    )


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
            "perf": 0,
            "console": 0,
            "send": 1,
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
                address = parse_byte_address(args.arguments[0])
                value = parse_integer(args.arguments[1], 0xFF, "byte value")
                client.write_byte(address, value)
                print(f"Written 0x{value:02x} at address 0x{address:04x}")
            elif args.command == "read-byte":
                address = parse_byte_address(args.arguments[0])
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
            elif args.command == "perf":
                cycles = client.get_cycles()
                instructions = client.get_instructions()
                if instructions == 0:
                    print(f"cycles={cycles} instructions=0 (CPI: sin datos)")
                else:
                    cpi = cycles / instructions
                    print(
                        f"cycles={cycles} instructions={instructions} "
                        f"CPI={cpi:.2f}"
                    )
            elif args.command == "console":
                interactive_console(client)
            elif args.command == "send":
                # Manda una cadena y ensena lo que conteste, sin terminal. Es
                # la forma de probar un programa interactivo desde un script.
                client.send_all(args.arguments[0].encode("latin-1"))
                time.sleep(0.2)
                respuesta = client.recv_bytes(255)
                print(respuesta.decode("latin-1"), end="")
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
