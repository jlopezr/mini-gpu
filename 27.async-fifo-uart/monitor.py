import argparse
import sys
from pathlib import Path

import serial

# Deteccion del puerto y listado: en tools/serial_ports.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.serial_ports import (  # noqa: E402
    PortError,
    available_ports,
    detect_port,
)

BAUD = 115200


def main():
    parser = argparse.ArgumentParser(description="Lee la salida serie de la FIFO")
    parser.add_argument("--port", "-P", default=None,
                        help="puerto serie; sin el, se detecta el FTDI")
    args = parser.parse_args()

    try:
        port = args.port if args.port is not None else detect_port()
    except PortError as error:
        sys.exit(f"error: {error}")

    try:
        ser = serial.Serial(port, BAUD, timeout=1)
    except serial.SerialException as error:
        sys.exit(f"error: no se pudo abrir {port}: {error}\n"
                 f"{available_ports()}")

    with ser:
        while True:
            line = ser.readline().decode(errors="replace").strip()

            if not line:
                continue

            print(line)

            if "ERR=1" in line:
                print("!!! ERROR EN LA FIFO !!!")

            if "PASS=1" in line:
                print("FIFO OK")


if __name__ == "__main__":
    main()
