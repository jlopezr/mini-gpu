#!/usr/bin/env python3
"""Lee de la placa los resultados de bench_dma.asm y los presenta en tablas.

Hay que haber corrido antes el benchmark y que la CPU esté parada (acaba con HALT):

    run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim/examples/asm/dma/bench_dma.asm
    python 32.cpu-gpu-func-sim/examples/asm/dma/bench_dma_report.py [--out tabla.md]

Lee 808 bytes desde `bench_done` con `monitor.py read-block` (la dirección sale de
ensamblar el propio programa) y los pasa a microsegundos y MB/s con el reloj de
la CPU, 80 MHz.
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

CLOCK_HZ = 80_000_000
OPERATIONS = ("memset", "memcpy", "fill_rect", "blit")
CONFIGS = ("CPU", "GPU 1w", "GPU 2w", "GPU 4w", "GPU 8w")
SIZES = (32, 64, 128, 256, 1024, 4096, 16384, 65536, 262144, 1048576)


def size_name(size: int) -> str:
    return f"{size} B" if size < 1024 else (f"{size // 1024} KiB" if size < 1 << 20 else "1 MiB")


def read_results(program: Path, port: str | None):
    source = program.read_text(encoding="utf-8")
    labels = first_pass(source, program.parent, program.name,
                        (ROOT / "x.tests" / "inc",), frozenset({"BOARD"}))[1]
    address = labels["bench_done"]
    with tempfile.TemporaryDirectory() as temp:
        block = Path(temp) / "bench.bin"
        command = [sys.executable, "-X", "utf8", str(ROOT / "36.fpga-cpu-gpu" / "monitor.py")]
        if port:
            command += ["--port", port]
        command += ["read-block", str(address), "808", str(block)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        data = block.read_bytes()
    done, errors = struct.unpack_from("<II", data, 0)
    cycles = struct.unpack_from("<200I", data, 8)
    return done, errors, cycles


def table(cycles, operation: int) -> str:
    out = [f"### {OPERATIONS[operation]}", "",
           "| Tamaño | " + " | ".join(CONFIGS) + " | mejor GPU | GPU / CPU |",
           "|---|" + "---:|" * (len(CONFIGS) + 2)]
    for index, size in enumerate(SIZES):
        row = [cycles[(operation * 10 + index) * 5 + c] for c in range(5)]
        micro = [c * 1e6 / CLOCK_HZ for c in row]
        cells = [f"{t:,.1f} µs ({size / t:,.1f} MB/s)" if t else "-" for t, _ in zip(micro, row)]
        best = min(range(1, 5), key=lambda c: row[c])
        ratio = row[0] / row[best] if row[best] else 0
        out.append(f"| {size_name(size)} | " + " | ".join(cells)
                   + f" | {CONFIGS[best]} | {ratio:.2f} x |")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--program", type=Path, default=HERE / "bench_dma.asm")
    parser.add_argument("--port")
    parser.add_argument("--out", type=Path, help="guarda además las tablas en este fichero")
    args = parser.parse_args()

    done, errors, cycles = read_results(args.program, args.port)
    if not done:
        print("el benchmark no ha terminado (bench_done = 0)", file=sys.stderr)
        return 1
    parts = [f"Fallos de comprobación: {errors}", ""]
    parts += [table(cycles, op) + "\n" for op in range(4)]
    text = "\n".join(parts)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
