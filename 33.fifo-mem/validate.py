#!/usr/bin/env python3
"""Prueba incremental automatizada del banco FIFO/fabric/SDRAM en placa."""

from __future__ import annotations

import argparse
import time

import serial

import monitor


CONTROL = 0x8120_0000
REQUESTS = (0x8120_0004, 0x8120_0020, 0x8120_0040)
ERRORS = (0x8120_0008, 0x8120_0024, 0x8120_0044)
MISMATCHES = (0x8120_000C, 0x8120_0028, 0x8120_0048)

WORD_TEST_ADDRESS = 0x0000_1000
WORD_TEST_VALUE = 0xA5C3_5A7E
BLOCK_TEST_ADDRESS = 0x0000_4000
BLOCK_TEST_DATA = bytes((index * 37 + 11) & 0xFF for index in range(4096))


class ValidationError(RuntimeError):
    """Una comprobacion funcional de la placa no ha dado el resultado esperado."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida monitor, SDRAM, CDC, fabric y generadores del prototipo 33."
    )
    parser.add_argument("--port", default=None)
    parser.add_argument("--baudrate", type=int, default=monitor.BAUDRATE)
    parser.add_argument("--serial-timeout", type=float, default=monitor.DEFAULT_TIMEOUT)
    parser.add_argument(
        "--step-seconds",
        type=float,
        default=2.0,
        help="Duracion de cada prueba incremental (por defecto: 2 s)",
    )
    parser.add_argument(
        "--soak-seconds",
        type=float,
        default=60.0,
        help="Duracion de la prueba sostenida (por defecto: 60 s)",
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_triplet(client: monitor.MonitorClient, addresses: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(client.read_word(address) for address in addresses)


def require_clean(client: monitor.MonitorClient) -> None:
    errors = read_triplet(client, ERRORS)
    mismatches = read_triplet(client, MISMATCHES)
    require(errors == (0, 0, 0), f"response errors: {errors}")
    require(mismatches == (0, 0, 0), f"data mismatches: {mismatches}")


def exercise_generators(
    client: monitor.MonitorClient,
    control: int,
    active: tuple[int, ...],
    seconds: float,
    label: str,
) -> tuple[int, int, int]:
    # Bit 8 genera el pulso CLEAR_STATS sin quedar almacenado en CONTROL.
    client.write_word(CONTROL, control | 0x100)
    require(client.read_word(CONTROL) == control, "CONTROL no conserva el valor escrito")
    before = read_triplet(client, REQUESTS)
    time.sleep(seconds)
    after = read_triplet(client, REQUESTS)
    deltas = tuple((right - left) & 0xFFFF_FFFF for left, right in zip(before, after))
    for generator in active:
        require(deltas[generator] > 0, f"GEN{generator} no progresa en {label}")
    require_clean(client)
    print(f"PASS {label}: requests +{deltas}")
    return deltas


def run(
    client: monitor.MonitorClient,
    step_seconds: float,
    soak_seconds: float,
    urgent_active: tuple[int, ...] = (0, 1, 2),
) -> None:
    client.ping()
    version = client.get_version()
    require((version.major, version.minor) == (1, 0), f"version inesperada: {version}")
    print("PASS monitor: PONG, version 1.0")

    client.write_word(CONTROL, 0)
    require(client.read_word(CONTROL) == 0, "MEMTEST CONTROL no responde como cero")
    print("PASS MEMTEST MMIO: CONTROL=0")

    original_word = client.read_word(WORD_TEST_ADDRESS)
    try:
        client.write_word(WORD_TEST_ADDRESS, WORD_TEST_VALUE)
        actual = client.read_word(WORD_TEST_ADDRESS)
        require(actual == WORD_TEST_VALUE, f"RAM word: 0x{actual:08x}")
        print("PASS RAM por p3: write-word/read-word")
    finally:
        client.write_word(WORD_TEST_ADDRESS, original_word)

    exercise_generators(client, 0x01, (0,), step_seconds, "GEN0")
    exercise_generators(client, 0x03, (0, 1), step_seconds, "GEN0+GEN1")
    exercise_generators(client, 0x07, (0, 1, 2), step_seconds, "GEN0+GEN1+GEN2")

    original_word = client.read_word(WORD_TEST_ADDRESS)
    try:
        client.write_word(WORD_TEST_ADDRESS, 0xDEAD_BEEF)
        actual = client.read_word(WORD_TEST_ADDRESS)
        require(actual == 0xDEAD_BEEF, f"RAM bajo contencion: 0x{actual:08x}")
        require_clean(client)
        print("PASS p3 bajo contencion")
    finally:
        client.write_word(WORD_TEST_ADDRESS, original_word)

    # Esta prueba ejercita el bit urgente y comprueba integridad/progreso. Con
    # una transaccion por generador en vuelo, los contadores no demuestran la
    # prioridad de latencia del arbitro; esa propiedad necesita un test dirigido.
    exercise_generators(client, 0x27, urgent_active, step_seconds, "GEN2 urgent")

    exercise_generators(client, 0x07, (0, 1, 2), soak_seconds, "soak")

    original_block = client.read_memory(BLOCK_TEST_ADDRESS, len(BLOCK_TEST_DATA))
    try:
        client.write_memory(BLOCK_TEST_ADDRESS, BLOCK_TEST_DATA)
        actual = client.read_memory(BLOCK_TEST_ADDRESS, len(BLOCK_TEST_DATA))
        require(actual == BLOCK_TEST_DATA, "el bloque leido por p3 no coincide")
        require_clean(client)
        print(f"PASS bloque p3 bajo contencion: {len(BLOCK_TEST_DATA)} bytes")
    finally:
        client.write_memory(BLOCK_TEST_ADDRESS, original_block)


def main() -> int:
    args = parse_args()
    if args.step_seconds <= 0 or args.soak_seconds <= 0:
        raise SystemExit("--step-seconds y --soak-seconds deben ser positivos")

    port = args.port if args.port is not None else monitor.detect_port()
    print(f"Puerto: {port}")

    with serial.Serial(
        port=port,
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
        client = monitor.MonitorClient(connection)
        original_control = client.read_word(CONTROL)
        try:
            run(client, args.step_seconds, args.soak_seconds)
        finally:
            client.write_word(CONTROL, original_control)

    print("PASS COMPLETO")
    print("Comprobacion manual pendiente: LED0/LED1 encendidos y LED5/LED6 apagados.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, monitor.MonitorError, monitor.PortError, serial.SerialException) as error:
        print(f"FAIL: {error}")
        raise SystemExit(1)
