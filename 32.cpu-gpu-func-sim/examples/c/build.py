#!/usr/bin/env python3
"""Compila un programa en C con CPU y GPU a una imagen para el simulador (y la placa).

    python examples/c/build.py examples/c/dma/memset.c [-o salida.bin] [--board]

Por cada .c (el programa y gpu.c): mini-lcc --no-crt, y mini-opt (intrinsecos y kernels).
Luego un .asm con el arranque (1.isa/runtime/crt0.s), los dos .s y el runtime de ensamblador
de la GPU (examples/asm/dma/gpu_runtime.inc), ensamblado con mini-asm. Todo queda en `_build/`.
Con --board: el runtime que lanza con RUN (la 36 no tiene WARP_START) y los ciclos de CPU
reales en `bench_now()`; la salida se llama `<nombre>_board.bin`.
Necesita y.lcc/build/rcc y un preprocesador de C (MSVC en Windows: lo busca mini-lcc).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "1.isa"))
from mini_asm import assemble_bytes, write_hex  # noqa: E402

SYSTEM = HERE / "system"
BUILD = HERE / "_build"
INCLUDE_DIRS = (ROOT / "x.tests" / "inc",)
CRT0 = ROOT / "1.isa" / "runtime" / "crt0.s"
ASM = HERE.parent / "asm"
# (runtime de la GPU, medida de ciclos): simulador y placa 36
RUNTIMES = {False: (ASM / "dma" / "gpu_runtime.inc", ASM / "race" / "bench_sim.inc"),
            True: (ASM / "dma" / "gpu_runtime_board.inc", ASM / "race" / "bench_board.inc")}


# programa -> (etiqueta, generador): datos binarios que se insertan tras el codigo con `.incbin`
# (el generador recibe `-o` y deja el .bin en _build/); el C los declara con `extern unsigned etiqueta[]`
DATA = {"plane": ("plane_tex", HERE / "race" / "plane_tex.py")}


class BuildError(RuntimeError):
    pass


def run(*command: str) -> None:
    done = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError(f"{' '.join(map(str, command))}\n{done.stdout}{done.stderr}")


def lower_c(source: Path) -> Path:
    """C -> .s sin arranque."""
    BUILD.mkdir(exist_ok=True)
    plain = BUILD / f"{source.stem}.s"
    run(TOOLS / "mini-lcc", source, "--no-crt", "-I", SYSTEM, "-o", plain)
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


def build(program: Path, output: Path | None = None, board: bool = False) -> Path:
    program = program.resolve()
    name = program.stem + ("_board" if board else "")
    output = output or BUILD / f"{name}.bin"
    runtime, bench = RUNTIMES[board]
    plains = [lower_c(program), lower_c(SYSTEM / "gpu.c")]
    fixed = [CRT0, runtime, bench]
    parts = [optimize_s(plain, fixed + [other for other in plains if other != plain]) for plain in plains]
    BUILD.mkdir(exist_ok=True)
    data = ""
    if program.stem in DATA:
        label, generator = DATA[program.stem]
        blob = BUILD / f"{label}.bin"
        run(generator, "-o", blob)
        data = f'.align 4\n{label}:\n.incbin "{blob.as_posix()}"\n'
    wrapper = BUILD / f"{name}.asm"
    wrapper.write_text(
        f'; generado por build.py\n.include "mmio.inc"\n.include "{CRT0.as_posix()}"\n'
        + "".join(f'.include "{part.as_posix()}"\n' for part in parts)
        + f'.include "{runtime.as_posix()}"\n.include "{bench.as_posix()}"\n' + data, encoding="utf-8")
    image = assemble_bytes(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                           INCLUDE_DIRS)
    output.write_bytes(image)
    write_hex(image, output.with_suffix(".hex"))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("program", type=Path, help="el .c con main y los kernels")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--board", action="store_true", help="para la placa 36 (RUN y ciclos reales)")
    args = parser.parse_args()
    try:
        out = build(args.program, args.output, args.board)
    except BuildError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
