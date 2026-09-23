"""`mini-dbg`: un depurador, dos sitios donde conectarlo.

    mini-dbg programa.asm                 # contra el simulador funcional
    mini-dbg --board -p 21                # contra la placa, por el monitor
    mini-dbg --board -p 21 programa.asm   # placa, con el fuente para el listado

El programa que se le pasa hace dos cosas: se carga en el simulador y sirve de
mapa `PC -> fuente`. Con `--board` no se carga nada --de eso ya se ocupa
`board-load`--, pero el fuente sigue valiendo para ver código en vez de
palabras, si es el que está en la placa.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import debug_source, sim_peripherals  # noqa: E402
from tools.debug_core import (  # noqa: E402
    CommandError, DEFAULT_RUN_LIMIT, DebugSession,
)
from tools.debug_target import SimTarget, TargetError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mini-dbg",
        description="Depurador interactivo de MiniCPU: simulador o placa.")
    parser.add_argument("program", type=Path, nargs="?",
                        help=".asm, .bin o .hex (obligatorio sin --board)")
    parser.add_argument("--board", action="store_true",
                        help="conecta a la placa por el monitor serie")
    parser.add_argument("--prototype", "-p", default=None,
                        help="prototipo de la placa (numero, nombre o ruta)")
    parser.add_argument("--port", default=None,
                        help="puerto serie; por defecto se autodetecta")
    parser.add_argument("--serial-timeout", type=float, default=2.0)
    parser.add_argument("--memory-size", type=lambda v: int(v, 0),
                        default=32 * 1024 * 1024,
                        help="memoria del simulador en bytes (admite 0x...)")
    parser.add_argument("--load-address", type=lambda v: int(v, 0), default=0,
                        help="direccion de carga en el simulador")
    parser.add_argument("--fb-layout", nargs="?", const="arnes",
                        metavar="FRONT[,BACK]",
                        help="coloca FB_FRONT/FB_BACK antes de arrancar, como "
                             "hace el arnes de x.tests; sin valor usa sus "
                             "mismas direcciones. Implica --video")
    parser.add_argument("--include", "-I", action="append", default=[],
                        type=Path, metavar="DIR",
                        help="carpeta extra para los .include; repetible. "
                             "x.tests/inc se busca siempre")
    parser.add_argument("--run-limit", type=int, default=DEFAULT_RUN_LIMIT,
                        help="tope de instrucciones de un `run` sin breakpoint")
    parser.add_argument("--break", dest="breakpoints", action="append",
                        default=[], metavar="X",
                        help="breakpoint inicial (direccion o etiqueta); repetible")
    parser.add_argument("--command", "-x", action="append", default=[],
                        metavar="CMD",
                        help="comando a ejecutar al arrancar; repetible")
    parser.add_argument("--no-tui", action="store_true",
                        help="modo linea, sin paneles (tuberias, ssh)")
    sim_peripherals.add_arguments(parser)
    return parser


def include_dirs(args) -> tuple[Path, ...]:
    """Dónde buscar los `.include`. `x.tests/inc` va siempre, como en
    `run-board`: es donde vive `mmio.inc` y casi todo caso de `x.tests` lo
    incluye, así que sin esto la mitad de los programas del repo no cargan."""
    return tuple(args.include) + (ROOT / "x.tests" / "inc",)


def load_program(path: Path, includes: tuple[Path, ...]) -> bytes:
    sys.path.insert(0, str(ROOT / "1.isa"))
    from mini_asm import assemble_bytes, load_program_bytes

    if path.suffix.lower() == ".asm":
        return assemble_bytes(path.read_text(encoding="utf-8"),
                              path.parent, path.name, includes)
    return load_program_bytes(path)


def apply_fb_layout(cpu, value: str) -> None:
    """Deja el framebuffer donde lo dejaría el arnés antes de correr un caso.

    `x.tests/backends/video_layout.py` explica por qué hace falta: desde la
    fase 3.5 las bases arrancan a cero, y casos como `band` o `bounce` leen
    FB_BACK y dibujan donde les digan. Sin esto dibujan sobre el propio
    programa en la dirección cero y mueren con un encoding inválido, que
    parece un fallo del caso y no lo es.

    Las direcciones se importan de allí, no se copian: ese fichero avisa de
    que `test_differential` compara framebuffers del simulador y de la placa
    byte a byte, y dos copias que se separen romperían la comparación.
    """
    from tools.sim_devices import VideoDevice

    sys.path.insert(0, str(ROOT / "x.tests"))
    from backends import video_layout

    front, back = video_layout.FB_FRONT, video_layout.FB_BACK
    if value != "arnes":
        partes = value.split(",")
        front = int(partes[0], 0)
        if len(partes) > 1:
            back = int(partes[1], 0)
        elif len(partes) == 1:
            # Un solo valor: el trasero, a un frame del frontal.
            back = front + VideoDevice.FRAME_BYTES if hasattr(
                VideoDevice, "FRAME_BYTES") else front + 320 * 240 * 2

    cpu.video.write(VideoDevice.FB_FRONT, front)
    cpu.video.write(VideoDevice.FB_BACK, back)


def open_simulator(args, includes: tuple[Path, ...]) -> SimTarget:
    sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))
    from minicpu_sim import CPU

    if args.fb_layout is not None:
        args.video = True
    cpu = CPU(args.memory_size, **sim_peripherals.from_arguments(args))
    cpu.load_program(load_program(args.program, includes), args.load_address)
    if args.fb_layout is not None:
        apply_fb_layout(cpu, args.fb_layout)
    return SimTarget(cpu)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.board and args.program is None:
        print("error: hace falta un programa, o --board para ir a la placa",
              file=sys.stderr)
        return 2
    if args.board and args.prototype is None:
        print("error: --board necesita --prototype", file=sys.stderr)
        return 2

    includes = include_dirs(args)
    connection = None
    try:
        if args.board:
            from tools.debug_board import connect

            target, connection = connect(
                args.prototype, args.port, args.serial_timeout)
        else:
            target = open_simulator(args, includes)
    except (TargetError, ValueError, OSError) as exc:
        # Un programa que no ensambla o una placa que no responde no son
        # fallos del depurador: se dicen y se sale, sin traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2

    source = (debug_source.from_program(args.program, includes)
              if args.program is not None else debug_source.SourceMap())
    session = DebugSession(target, source, run_limit=args.run_limit)

    startup = [f"break {mark}" for mark in args.breakpoints] + args.command
    try:
        for command in startup:
            for line in session.execute(command):
                print(line)
    except (CommandError, TargetError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        from tools.debug_tui import run_line_mode, run_tui

        if args.no_tui:
            return run_line_mode(session)
        if importlib.util.find_spec("textual") is None:
            print("aviso: sin `textual` instalado; modo linea "
                  "(pip install -r requirements.txt)", file=sys.stderr)
            return run_line_mode(session)
        return run_tui(session)
    finally:
        # Se salga como se salga --`quit`, Ctrl-C o cerrando la TUI-- no se
        # deja detrás ni el puerto abierto ni una ventana huérfana.
        session.close_video()
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
