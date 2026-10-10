"""Compila un programa en C con CPU y GPU a una imagen para el simulador (y la placa).

    build-c programa.c [-o salida.bin] [--outdir DIR] [-I DIR]... [--data ETIQUETA=FICHERO]... [--board]
                       [--load [PROTOTIPO]] [--no-run]

Por cada .c (el programa y x.tests/runtime/gpu/gpu.c): mini-lcc --no-crt, y mini-opt (intrinsecos y
kernels). Luego un .asm con el arranque (1.isa/runtime/crt0.s), los dos .s y el runtime de la GPU
(x.tests/inc/gpu_runtime.inc y bench.inc), ensamblado con mini-asm. Todo queda en `--outdir`.
Con --board: el runtime que lanza con RUN (la 36 no tiene WARP_START) y los ciclos de CPU reales en
`bench_now()`; la salida se llama `<nombre>_board.bin`.
--data pega un fichero binario tras el codigo, con `.incbin`, bajo una etiqueta que el C declara con
`extern unsigned etiqueta[]`. Quien lo genera es quien llama, no esta herramienta.
--load sube la imagen a la placa (implica --board; PROTOTIPO por defecto 36) con la misma carga que
`board-load`: no comprueba el bitstream. --no-run la carga sin arrancarla.
Necesita y.lcc/build/rcc y un preprocesador de C (MSVC en Windows: lo busca mini-lcc).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "1.isa"))
from mini_asm import assemble_bytes, write_hex  # noqa: E402

INC = ROOT / "x.tests" / "inc"                 # gpu.h, mmio.h, mmio.inc, gpu_runtime.inc, bench.inc
GPU_C = ROOT / "x.tests" / "runtime" / "gpu" / "gpu.c"
CRT0 = ROOT / "1.isa" / "runtime" / "crt0.s"
INCLUDE_DIRS = (INC,)
DEFAULT_OUTDIR = ROOT / "_build" / "c"


class BuildError(RuntimeError):
    pass


def run(*command: str) -> None:
    done = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError(f"{' '.join(map(str, command))}\n{done.stdout}{done.stderr}")


def lower_c(source: Path, outdir: Path, includes: tuple[Path, ...] = ()) -> Path:
    """C -> .s sin arranque."""
    outdir.mkdir(parents=True, exist_ok=True)
    plain = outdir / f"{source.stem}.s"
    flags = [arg for folder in (INC, *includes) for arg in ("-I", folder)]
    run(TOOLS / "mini-lcc", source, "--no-crt", *flags, "-o", plain)
    return plain


def optimize_s(plain: Path, foreign: list[Path]) -> Path:
    """.s -> .s con los pases de mini-opt. `foreign`: lo que se ensambla aparte y puede nombrar sus simbolos (el
    arranque, el runtime, la otra unidad): un simbolo que nombran no se da por privado de esta."""
    optimized = plain.with_suffix(".opt.s")
    passes = os.environ.get("MINI_OPT_PASSES")       # para comparar (opt_stats.py); por defecto, todos
    # por defecto, mini-opt solo saca de un bucle la carga de una global que ningun puntero puede alcanzar. Con
    # MINI_OPT_NOALIAS=1 basta que el kernel no la escriba (--assume-noalias), aunque su direccion escape
    noalias = ["--assume-noalias"] if os.environ.get("MINI_OPT_NOALIAS") == "1" else []
    refs = [arg for path in foreign for arg in ("--extern-refs", path)]
    run(TOOLS / "mini-opt", plain, "-o", optimized, *noalias, *refs,
        *(["--passes", passes] if passes is not None else []))
    return optimized


def image_name(program: Path, board: bool = False) -> str:
    return program.stem + ("_board" if board else "")


def wrapper_path(program: Path, board: bool = False, outdir: Path | None = None) -> Path:
    """El .asm que une el arranque, las dos unidades y el runtime: lo que `build` ensambla."""
    return (outdir or DEFAULT_OUTDIR) / f"{image_name(program, board)}.asm"


def build(program: Path, output: Path | None = None, board: bool = False,
          outdir: Path | None = None, includes: tuple[Path, ...] = (),
          data: tuple[tuple[str, Path], ...] = ()) -> Path:
    """`data`: (etiqueta, fichero) de cada binario que se pega tras el codigo."""
    program = program.resolve()
    outdir = (outdir or DEFAULT_OUTDIR).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    output = output or outdir / f"{image_name(program, board)}.bin"
    runtime, bench = INC / "gpu_runtime.inc", INC / "bench.inc"
    plains = [lower_c(program, outdir, includes), lower_c(GPU_C, outdir, includes)]
    fixed = [CRT0, runtime, bench]
    parts = [optimize_s(plain, fixed + [other for other in plains if other != plain]) for plain in plains]
    blobs = "".join(f'.align 4\n{label}:\n.incbin "{Path(path).resolve().as_posix()}"\n' for label, path in data)
    wrapper = wrapper_path(program, board, outdir)
    wrapper.write_text(
        "; generado por build-c\n" + (".define BOARD\n" if board else "")
        + f'.include "mmio.inc"\n.include "{CRT0.as_posix()}"\n'
        + "".join(f'.include "{part.as_posix()}"\n' for part in parts)
        + '.include "gpu_runtime.inc"\n.include "bench.inc"\n' + blobs, encoding="utf-8")
    image = assemble_bytes(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                           INCLUDE_DIRS)
    output.write_bytes(image)
    write_hex(image, output.with_suffix(".hex"))
    return output


def parse_data(text: str) -> tuple[str, Path]:
    label, separator, path = text.partition("=")
    if not separator or not label.isidentifier() or not path:
        raise argparse.ArgumentTypeError(f"--data espera ETIQUETA=FICHERO, no {text!r}")
    return label, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("program", type=Path, help="el .c con main y los kernels")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--outdir", type=Path, help=f"carpeta de los intermedios (por defecto {DEFAULT_OUTDIR})")
    parser.add_argument("-I", dest="includes", action="append", type=Path, default=[], metavar="DIR",
                        help="carpeta extra para #include (repetible); x.tests/inc va siempre")
    parser.add_argument("--data", action="append", type=parse_data, default=[], metavar="ETIQUETA=FICHERO",
                        help="pega un binario tras el codigo con esa etiqueta (repetible)")
    parser.add_argument("--board", action="store_true", help="para la placa 36 (RUN y ciclos reales)")
    parser.add_argument("--load", nargs="?", const="36", metavar="PROTOTIPO",
                        help="sube la imagen a la placa tras compilar (implica --board; por defecto la 36)")
    parser.add_argument("--no-run", action="store_true", help="con --load, la carga pero no la arranca")
    args = parser.parse_args(argv)
    board = args.board or args.load is not None
    try:
        out = build(args.program, args.output, board, args.outdir, tuple(args.includes), tuple(args.data))
    except BuildError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{out} ({out.stat().st_size} bytes)")
    if args.load is None:
        return 0
    sys.path.insert(0, str(TOOLS))
    import run_board
    return run_board.main_load(["-p", args.load, "--program", str(out)] + (["--no-run"] if args.no_run else []))


if __name__ == "__main__":
    raise SystemExit(main())
