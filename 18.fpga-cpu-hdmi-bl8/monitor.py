#!/usr/bin/env python3
"""Command-line client for the minimal FPGA UART monitor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import serial

# 1 Mbaud: el dominio de CPU corre a 100 MHz y el divisor es 100. Ese divisor
# es múltiplo de 4, que es lo que necesita la recepción de `uart.v` (muestrea
# a 4x con DIVISOR/4, y la división es entera), y 1 Mbaud es además 3 MHz / 3,
# que el generador del FTDI produce exacto. Ver el comentario de `top.v`.
BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0x01FF_FFFF
# Registros de vídeo: FB_FRONT, FB_BACK, SWAP y STATUS.
MMIO_BASE = 0x8000_0000
# 32 bytes, no 16: la 18 anade SWAP_COUNT (0x10) y HALT_AT (0x14) a los cuatro
# registros que venian de la 16.
MMIO_LIMIT = 0x8000_0FFF
# Espacio físico unificado: la CPU y el monitor ven las mismas direcciones.
ARCHITECTURAL_REGIONS = (
    (0x0000_0000, 0x0200_0000),
)
# Bloque de video en MMIO: FB_FRONT, FB_BACK, SWAP, STATUS, SWAP_COUNT, HALT_AT.
# Solo filtra bloques y transferencias (validate_block / validate_transfer); los
# accesos byte a byte no pasan por aqui, que es por lo que esta lista pudo estar
# vacia sin que se notara. El RTL si acepta un bloque sobre el MMIO: en el
# adaptador la rama is_mmio va antes de la comprobacion de cpu_halted.
# Una region por BLOQUE de MMIO v2. Antes era UNA sola --la pagina de 4 KiB
# entera, `address[31:12] == 20'h80000`, dieciseis dispositivos de 256 B--
# porque todos los dispositivos cabian dentro; ahora estan a megabytes unos de
# otros. Son las gemelas de los WINDOWn_* del `top.v`, y son TRES porque esta
# carpeta no tiene puerto serie.
#
# Un subconjunto seria una tercera gemela que mantener, y ya se quedo atras una
# vez: estuvo en 0x8000_0018 con un comentario que decia "llegara a
# 0x8000_001c cuando la fase 3.5 anada VIDEO_CTRL", la fase lo anadio y la
# constante se quedo, asi que el host rechazaba un bloque sobre el registro que
# acababa de existir. Por eso cada region es el BLOQUE entero y no los
# registros que hoy existen dentro.
#
# Los numeros van LITERALES y no derivados del mapa, aunque el mapa este
# importado: `tools/prototype_report.py` lee esta asignacion del TEXTO del
# fichero, sin importar el modulo, y un `tuple(... for ...)` lo deja ciego.
# Escribirlos a mano es obligatorio; dejarlos sin comprobar, no: hay un test que
# los contrasta contra el mapa generado y otro contra los WINDOWn_* del top.v.
MONITOR_REGIONS = (
    (0x8000_0000, 0x8001_0000),     # SYSTEM
    (0x8020_0000, 0x8021_0000),     # VIDEO
    (0x8101_0000, 0x8102_0000),     # CPU PERFORMANCE
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
    PerfMixin,
)

# El cuerpo de una clase no puede LEER un global que ademas asigna, asi
# que estos alias son lo que permite que el atributo de clase y la
# constante del modulo -que es la que se lee desde fuera- se llamen
# igual.
_REGIONES = MEMORY_REGIONS


class MonitorClient(PerfMixin, protocolo.MonitorClient):
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
            "perf",
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


def parse_address(value: str) -> int:
    """Dirección para CUALQUIER comando: SDRAM o la ventana de registros.

    Los registros de vídeo viven en `MMIO_BASE` y no son memoria, pero eso no
    los hace exclusivos del acceso byte a byte, que es lo que esto daba por
    supuesto mientras se llamaba `parse_byte_address` y sólo lo usaban
    `read-byte`/`write-byte`. El RTL atiende una palabra y un bloque sobre el
    MMIO igual que sobre la SDRAM --en el adaptador la rama `is_mmio` va antes
    de la comprobación de `cpu_halted`-- y `MONITOR_REGIONS` abre la página
    entera justamente para que `validate_block` los deje pasar. El resto de
    comandos usaba un tope de 32 MiB que sólo describe la SDRAM, así que
    `read-word 0x80000300` --el contador de ciclos que `perf` sí lee-- se
    rechazaba en el cliente y la única forma de verlo a mano era juntar cuatro
    `read-byte`: exactamente la lectura desgarrada que `read_word` existe para
    evitar.

    Al contrario que la memoria, estos registros responden también con la CPU
    en marcha, que es lo que permite leer el contador de frames o mover el
    framebuffer mientras un programa dibuja.
    """
    try:
        result = int(value, 0)
    except ValueError as error:
        raise MonitorError(f"Invalid address: {value}") from error

    if 0 <= result <= MAX_ADDRESS or MMIO_BASE <= result <= MMIO_LIMIT:
        return result

    raise MonitorError(
        f"Address must be between 0 and 0x{MAX_ADDRESS:x}, "
        f"or inside the MMIO register window "
        f"0x{MMIO_BASE:08x}-0x{MMIO_LIMIT:08x}"
    )


def test_pattern(number: int, address: int, length: int) -> bytes:
    """Build one deterministic SDRAM test pattern for a physical byte range."""
    if number == 0:
        return bytes(length)
    if number == 1:
        return bytes((0xFF,)) * length
    if number == 2:
        return bytes(((address + offset) ^ 0xA5) & 0xFF for offset in range(length))
    return bytes(0xAA if (address + offset) & 1 else 0x55 for offset in range(length))


# Los comandos que tocan la memoria del sistema. Todos empiezan por una
# dirección y ninguno de los demás la tiene, que es lo que permite hacer la
# comprobación de `require_halted` en UN sitio (ver `main`) en vez de
# repetirla en las siete ramas del despacho.
MEMORY_COMMANDS = frozenset({
    "write-byte",
    "read-byte",
    "read-word",
    "write-word",
    "write-block",
    "read-block",
    "verify",
    "memory-test",
})


def require_halted(client: MonitorClient, command: str, address: int) -> None:
    """La SDRAM sólo se deja tocar por el monitor con el núcleo parado.

    No es sólo cosa de las escrituras: en el adaptador, la rama de SDRAM
    contesta `mem_error` si `!cpu_halted` sin mirar si la petición era de
    lectura (`monitor_mem_adapter_128.v`, el `else if (!cpu_halted ||
    !init_done || !address_in_sdram)`). Así que `read-block` y `verify`
    fallaban igual de mal que `write-block`, y el cliente traducía el `ff` a
    "The FPGA rejected the command": verdad, pero no dice lo único que hay que
    hacer.

    Se PREGUNTA en vez de parar por las bravas. Un `halt` automático mataría
    la demo que estuviera corriendo, y quien lanza un test destructivo quiere
    enterarse de eso antes y no después.

    El MMIO queda fuera a propósito, y sale antes de hablar con la placa: esos
    registros responden en marcha --es justo cuando tiene gracia mirarlos-- y
    así `capture-frames`, que lee los registros de vídeo de cuatro en cuatro
    bytes, no paga una consulta de estado por cada byte.
    """
    if MMIO_BASE <= address <= MMIO_LIMIT:
        return
    if not client.get_status().halted:
        raise MonitorError(
            f"{command} necesita la CPU parada: el monitor no puede leer ni "
            f"escribir memoria con el núcleo en marcha. Ejecuta "
            f"`monitor.py halt` (o `reset`) antes."
        )


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
            "perf": 0,
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

            # Antes de nada, y una sola vez: si el comando toca memoria y la
            # CPU sigue corriendo, decirlo con esas palabras en vez de dejar
            # que la placa conteste `ff` mas abajo.
            if args.command in MEMORY_COMMANDS:
                require_halted(
                    client, args.command, parse_address(args.arguments[0]))

            if args.command == "ping":
                client.ping()
                print("PONG: FPGA monitor is responding")
            elif args.command == "get-version":
                version = client.get_version()
                print(f"FPGA monitor version: {version}")
            elif args.command == "write-byte":
                address = parse_address(args.arguments[0])
                value = parse_integer(args.arguments[1], 0xFF, "byte value")
                client.write_byte(address, value)
                print(f"Written 0x{value:02x} at address 0x{address:04x}")
            elif args.command == "read-byte":
                address = parse_address(args.arguments[0])
                value = client.read_byte(address)
                print(f"Address 0x{address:04x}: 0x{value:02x}")
            elif args.command == "read-word":
                address = parse_address(args.arguments[0])
                value = client.read_word(address)
                print(f"Address 0x{address:08x}: 0x{value:08x}")
            elif args.command == "write-word":
                address = parse_address(args.arguments[0])
                value = parse_integer(args.arguments[1], 0xFFFF_FFFF, "word value")
                client.write_word(address, value)
                print(f"Written 0x{value:08x} at address 0x{address:08x}")
            elif args.command == "write-block":
                address = parse_address(args.arguments[0])
                source = Path(args.arguments[1])
                data = source.read_bytes()
                client.write_memory(address, data)
                print(f"Written {len(data)} byte(s) at address 0x{address:04x}")
            elif args.command == "read-block":
                address = parse_address(args.arguments[0])
                length = parse_integer(args.arguments[1], MAX_ADDRESS + 1, "length")
                destination = Path(args.arguments[2])
                data = client.read_memory(address, length)
                destination.write_bytes(data)
                print(
                    f"Read {len(data)} byte(s) from address 0x{address:04x} "
                    f"into {destination}"
                )
            elif args.command == "verify":
                address = parse_address(args.arguments[0])
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
                address = parse_address(args.arguments[0])
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
