#!/usr/bin/env python3
"""Compila el BASIC para MiniCPU y lo ejecuta en 2.cpu-sim-func con la UART.

    python run_minicpu.py                      # interactivo: teclado y pantalla
    python run_minicpu.py programa.bas         # por lotes: el fichero es la entrada
    python run_minicpu.py -                    # por lotes, el texto llega por stdin

Por lotes, el fichero se entrega entero por la entrada serie y la sesion termina
cuando se acaba (basic_mini.c define BASIC_UART_EOF). En modo interactivo el
teclado alimenta la UART mientras el simulador corre (basic_mini_tty.c espera
teclas); Ctrl+C sale.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BUILD = HERE / "_build"


def compile_basic(source: Path, asm: Path) -> int:
    return subprocess.call([sys.executable, str(REPO / "tools" / "mini-lcc"),
                            str(source), "-o", str(asm)])


def run_batch(args) -> int:
    asm = BUILD / "basic.asm"
    text = sys.stdin.buffer.read() if args.program == "-" else Path(args.program).read_bytes()
    # La UART recibe bytes de teclado. mb_repl acaba la linea con \r o con \n,
    # asi que CRLF seria dos Enter: se normaliza a \n.
    text = text.replace(b"\r\n", b"\n")
    (BUILD / "input.txt").write_bytes(text)

    if not (args.no_build and asm.exists()):
        code = compile_basic(HERE / "basic_mini.c", asm)
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


class Keyboard:
    """Teclas sueltas, sin eco y sin esperar a Enter. Windows y POSIX."""

    def __enter__(self):
        if sys.platform == "win32":
            import msvcrt
            self._msvcrt = msvcrt
        else:
            import termios
            import tty
            self._termios = termios
            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc):
        if sys.platform != "win32":
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._saved)

    def read(self) -> bytes:
        """Los bytes pendientes; vacio si no se ha pulsado nada."""
        out = bytearray()
        if sys.platform == "win32":
            while self._msvcrt.kbhit():
                ch = self._msvcrt.getwch()
                if ch in ("\x00", "\xe0"):      # tecla de funcion o flecha: su 2o byte
                    self._msvcrt.getwch()
                    continue
                out += ch.encode("latin-1", "replace")
        else:
            import select
            while select.select([sys.stdin], [], [], 0)[0]:
                data = sys.stdin.buffer.read1(64)
                if not data:
                    break
                out += data
        return bytes(out)


def run_interactive(args) -> int:
    asm = BUILD / "basic_tty.asm"
    if not (args.no_build and asm.exists()):
        code = compile_basic(HERE / "basic_mini_tty.c", asm)
        if code:
            return code

    sys.path.insert(0, str(REPO / "2.cpu-sim-func"))
    import minicpu_sim

    serial = minicpu_sim.SerialDevice()
    cpu = minicpu_sim.CPU(serial=serial)
    cpu.load_program(minicpu_sim.load_program_file(asm))

    sys.stderr.write("BASIC en MiniCPU (simulador). Ctrl+C para salir.\n")
    stdout = sys.stdout.buffer
    pending = b""                                            # teclas aun sin sitio en la cola
    try:
        with Keyboard() as keyboard:
            while not cpu.halted:
                keys = keyboard.read()
                if b"\x03" in keys:                         # Ctrl+C
                    break
                pending += keys.replace(b"\r\n", b"\r")
                if pending:
                    room = max(0, serial.depth - len(serial.rx))
                    pending = pending[serial.push(pending[:room]):] + pending[room:]
                produced = False
                for _ in range(args.chunk):
                    cpu.step()
                    if cpu.halted:
                        break
                out = serial.pop(255)
                while out:
                    produced = True
                    stdout.write(out)
                    out = serial.pop(255)
                stdout.flush()
                # Sin nada que hacer, el BASIC solo sondea el estado de la UART:
                # se cede la CPU del anfitrion en vez de girar al maximo.
                if not produced and not serial.rx and not pending:
                    time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    print()
    if cpu.error:
        print(f"ERROR 0x{cpu.error_code:02X} en PC=0x{cpu.error_pc:08X} "
              f"tras {cpu.instructions_executed} instrucciones", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", nargs="?",
                        help="fuente BASIC, o - para stdin; sin argumento, interactivo")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="teclado y pantalla en vivo (por defecto sin `program`)")
    parser.add_argument("--max", type=int, default=200_000_000,
                        help="tope de instrucciones del simulador (por lotes)")
    parser.add_argument("--chunk", type=int, default=5000,
                        help="instrucciones entre lecturas del teclado (interactivo)")
    parser.add_argument("--no-build", action="store_true",
                        help="reutiliza el .asm de _build si ya existe")
    args = parser.parse_args()

    BUILD.mkdir(exist_ok=True)
    if args.interactive or args.program is None:
        return run_interactive(args)
    return run_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
