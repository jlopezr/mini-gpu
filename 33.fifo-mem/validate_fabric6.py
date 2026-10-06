#!/usr/bin/env python3
"""Validacion en placa del top_fabric6 de seis puertos."""

from __future__ import annotations

import time

import serial

import monitor
import validate


EXTRA_ADDRESSES = (0x8120_0060, 0x8120_0080)
EXTRA_STATUS = (0x8120_0064, 0x8120_0084)


def require_extra_generators(client: monitor.MonitorClient, seconds: float) -> None:
    client.write_word(validate.CONTROL, 0x104)
    before = validate.read_triplet(client, EXTRA_ADDRESSES)
    time.sleep(seconds)
    after = validate.read_triplet(client, EXTRA_ADDRESSES)
    client.write_word(validate.CONTROL, 0)
    status = validate.read_triplet(client, EXTRA_STATUS)

    validate.require(
        all(left != right for left, right in zip(before, after)),
        "GEN4/GEN5 no progresan; comprueba que esta cargado top_fabric6 "
        f"(address before={before}, after={after})",
    )
    validate.require(status == (0, 0), f"GEN4/GEN5 status de error: {status}")
    print(f"PASS GEN4+GEN5: address {before} -> {after}, status=0")


def main() -> int:
    args = validate.parse_args()
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
        original_control = client.read_word(validate.CONTROL)
        try:
            # La regresion base valida monitor, p3, los tres generadores
            # originales, urgent y carga sostenida. En top_fabric6, GEN4 y
            # GEN5 comparten enable/urgent con GEN2 y trabajan en paralelo.
            # En fabric6, el control urgente de GEN2 gobierna p2, p4 y p5.
            # Los tres pueden mantener siempre alguna peticion urgente y, con
            # prioridad estricta, GEN0/GEN1 normales no tienen por que avanzar
            # durante esa ventana. La regresion base solo exige avance a GEN2;
            # debajo se comprueba por separado el avance de GEN4 y GEN5.
            validate.run(
                client,
                args.step_seconds,
                args.soak_seconds,
                urgent_active=(2,),
            )
            require_extra_generators(client, args.step_seconds)
        finally:
            client.write_word(validate.CONTROL, original_control)

    print("PASS FABRIC6 COMPLETO")
    print("Comprobacion manual pendiente: LED0/LED1 encendidos y LED5/LED6 apagados.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        validate.ValidationError,
        monitor.MonitorError,
        monitor.PortError,
        serial.SerialException,
    ) as error:
        print(f"FAIL: {error}")
        raise SystemExit(1)
