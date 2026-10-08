#!/usr/bin/env python3
"""Lee de la placa los resultados de lat_exp_board.asm: la latencia de un acceso.

    run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim/examples/asm/dma/lat_exp_board.asm
    python 32.cpu-gpu-func-sim/examples/asm/dma/lat_exp_report.py [--out tabla.md]

La CPU tiene que estar parada (el programa acaba con HALT). Lee 484 bytes desde
`lat_done`. La latencia de un acceso es (ciclos con acceso - ciclos de la línea
base, el mismo bucle sin acceso) / N, en ciclos de GPU (25 MHz).
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "1.isa"))
from mini_asm import first_pass  # noqa: E402

GPU_HZ = 25_000_000
KERNELS = ("sin acceso (línea base)", "load", "store")
STRIDES = (0, 16, 64, 256, 1024, 4096, 16384, 65536)


def read_results(program: Path, port: str | None):
    source = program.read_text(encoding="utf-8")
    labels = first_pass(source, program.parent, program.name,
                        (ROOT / "x.tests" / "inc",))[1]
    with tempfile.TemporaryDirectory() as temp:
        block = Path(temp) / "lat.bin"
        command = [sys.executable, "-X", "utf8", str(ROOT / "36.fpga-cpu-gpu" / "monitor.py")]
        if port:
            command += ["--port", port]
        command += ["read-block", str(labels["lat_done"]), "484", str(block)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        data = block.read_bytes()
    done = struct.unpack_from("<I", data, 0)[0]
    rows = [struct.unpack_from("<5I", data, 4 + 20 * i) for i in range(24)]
    return done, rows


def table(rows) -> str:
    out = ["| Kernel | Stride | N | Ciclos GPU | Ciclos por vuelta | Instrucciones | Ciclos por instrucción"
           " | Fallos IMEM | Transacciones | Latencia del acceso (ciclos) | (ns) |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, name in enumerate(KERNELS):
        for s, stride in enumerate(STRIDES):
            cycles, tx, n, retired, misses = rows[k * 8 + s]
            per = cycles / n
            if k == 0:
                extra = "-"
                ns = "-"
            else:
                base = rows[s][0] / rows[s][2]
                extra = f"{per - base:.1f}"
                ns = f"{(per - base) * 1e9 / GPU_HZ:.0f}"
            out.append(f"| {name} | {stride} | {n} | {cycles:,} | {per:.1f} | {retired:,} "
                       f"| {cycles / retired if retired else 0:.1f} | {misses:,} | {tx:,} | {extra} | {ns} |")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--program", type=Path, default=HERE / "lat_exp_board.asm")
    parser.add_argument("--port")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    done, rows = read_results(args.program, args.port)
    if not done:
        print("el experimento no ha terminado (lat_done = 0)", file=sys.stderr)
        return 1
    text = table(rows) + "\n"
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
