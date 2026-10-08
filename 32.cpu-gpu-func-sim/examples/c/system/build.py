#!/usr/bin/env python3
"""Compila un programa en C con CPU y GPU a una imagen para el simulador (y la placa).

    python examples/c/system/build.py examples/c/dma/memset.c [-o salida.bin]

Por cada .c (el programa y gpu.c): mini-lcc --no-crt, y mini-opt (intrinsecos y kernels).
Luego un .asm con el arranque (1.isa/runtime/crt0.s), los dos .s y el runtime de ensamblador
de la GPU (examples/asm/dma/gpu_runtime.inc), ensamblado con mini-asm. Todo queda en `_build/`.
Necesita y.lcc/build/rcc y un preprocesador de C (MSVC en Windows: lo busca mini-lcc).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "1.isa"))
from mini_asm import assemble_bytes, write_hex  # noqa: E402

BUILD = HERE.parent / "_build"
INCLUDE_DIRS = (ROOT / "x.tests" / "inc",)
CRT0 = ROOT / "1.isa" / "runtime" / "crt0.s"
GPU_RUNTIME = HERE.parents[1] / "asm" / "dma" / "gpu_runtime.inc"


class BuildError(RuntimeError):
    pass


def run(*command: str) -> None:
    done = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError(f"{' '.join(map(str, command))}\n{done.stdout}{done.stderr}")


def compile_c(source: Path) -> Path:
    """C -> .s sin arranque -> .s con los pases de mini-opt."""
    BUILD.mkdir(exist_ok=True)
    plain = BUILD / f"{source.stem}.s"
    optimized = BUILD / f"{source.stem}.opt.s"
    run(TOOLS / "mini-lcc", source, "--no-crt", "-I", HERE, "-o", plain)
    run(TOOLS / "mini-opt", plain, "-o", optimized)
    return optimized


def build(program: Path, output: Path | None = None) -> Path:
    program = program.resolve()
    output = output or BUILD / f"{program.stem}.bin"
    parts = [compile_c(program), compile_c(HERE / "gpu.c")]
    BUILD.mkdir(exist_ok=True)
    wrapper = BUILD / f"{program.stem}.asm"
    wrapper.write_text(
        f'; generado por build.py\n.include "mmio.inc"\n.include "{CRT0.as_posix()}"\n'
        + "".join(f'.include "{part.as_posix()}"\n' for part in parts)
        + f'.include "{GPU_RUNTIME.as_posix()}"\n', encoding="utf-8")
    image = assemble_bytes(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                           INCLUDE_DIRS)
    output.write_bytes(image)
    write_hex(image, output.with_suffix(".hex"))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("program", type=Path, help="el .c con main y los kernels")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    try:
        out = build(args.program, args.output)
    except BuildError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
