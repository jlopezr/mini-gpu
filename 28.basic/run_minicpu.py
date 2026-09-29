#!/usr/bin/env python3
"""Compila el BASIC para MiniCPU y lo ejecuta en 2.cpu-sim-func con la UART.

    python run_minicpu.py programa.bas         # una linea BASIC por linea
    python run_minicpu.py -                    # el texto llega por stdin

El fichero se entrega entero por la entrada serie y la sesion termina cuando se
acaba (basic_mini.c define BASIC_UART_EOF). La salida serie va a stdout.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BUILD = HERE / "_build"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", help="fuente BASIC, o - para stdin")
    parser.add_argument("--max", type=int, default=200_000_000,
                        help="tope de instrucciones del simulador")
    parser.add_argument("--no-build", action="store_true",
                        help="reutiliza _build/basic.asm si ya existe")
    args = parser.parse_args()

    BUILD.mkdir(exist_ok=True)
    asm = BUILD / "basic.asm"
    text = sys.stdin.buffer.read() if args.program == "-" else Path(args.program).read_bytes()
    # La UART recibe bytes de teclado: el fin de linea es CR LF.
    text = text.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    (BUILD / "input.txt").write_bytes(text)

    if not (args.no_build and asm.exists()):
        code = subprocess.call([sys.executable, str(REPO / "tools" / "mini-lcc"),
                                str(HERE / "basic_mini.c"), "-o", str(asm)])
        if code:
            return code

    out = BUILD / "output.txt"
    out.unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, str(REPO / "2.cpu-sim-func" / "minicpu_sim.py"), str(asm),
         "--serial-input", str(BUILD / "input.txt"), "--serial-output", str(out),
         "--max", str(args.max)],
        capture_output=True, text=True)
    if out.exists():
        sys.stdout.buffer.write(out.read_bytes())
        sys.stdout.flush()
    if result.returncode or "ERROR" in result.stdout:
        print(result.stdout + result.stderr, file=sys.stderr)
        return result.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
