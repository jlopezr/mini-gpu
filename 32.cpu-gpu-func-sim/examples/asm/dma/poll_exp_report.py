#!/usr/bin/env python3
"""Lee de la placa los resultados de poll_exp_board.asm y los presenta en una tabla.

    run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim/examples/asm/dma/poll_exp_board.asm
    python 32.cpu-gpu-func-sim/examples/asm/dma/poll_exp_report.py [--out tabla.md]

La CPU tiene que estar parada (el programa acaba con HALT). Lee 584 bytes desde
`exp_done`: el fin, los fallos y las 24 filas de cuatro palabras.
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
CPU_HZ = 80_000_000
BYTES = 256 * 1024
OPERATIONS = ("memset", "memcpy")
WARPS = (1, 2, 4, 8)
MODES = ("sondeo continuo", "sondeo con pausa", "sin sondear")


def read_results(program: Path, port: str | None):
    source = program.read_text(encoding="utf-8")
    labels = first_pass(source, program.parent, program.name,
                        (ROOT / "x.tests" / "inc",))[1]
    with tempfile.TemporaryDirectory() as temp:
        block = Path(temp) / "exp.bin"
        command = [sys.executable, "-X", "utf8", str(ROOT / "36.fpga-cpu-gpu" / "monitor.py")]
        if port:
            command += ["--port", port]
        command += ["read-block", str(labels["exp_done"]), "584", str(block)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        data = block.read_bytes()
    done, errors = struct.unpack_from("<II", data, 0)
    rows = [struct.unpack_from("<6I", data, 8 + 24 * i) for i in range(24)]
    return done, errors, rows


def table(rows) -> str:
    out = ["| Operación | Warps | Modo de espera | Ciclos GPU | Transacciones | Ciclos GPU por transacción"
           " | Instrucciones de warp | Ciclos por instrucción | Fallos IMEM"
           " | Espera de memoria | MB/s (reloj de la GPU) | Ciclos CPU |",
           "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for op, name in enumerate(OPERATIONS):
        for w, warps in enumerate(WARPS):
            for mode, label in enumerate(MODES):
                cycles, tx, stall, cpu, retired, misses = rows[(op * 4 + w) * 3 + mode]
                per_tx = cycles / tx if tx else 0
                per_instr = cycles / retired if retired else 0
                mbs = BYTES / (cycles / GPU_HZ) / 1e6 if cycles else 0
                out.append(f"| {name} | {warps} | {label} | {cycles:,} | {tx:,} | {per_tx:.1f} "
                           f"| {retired:,} | {per_instr:.1f} | {misses:,} "
                           f"| {stall / cycles * 100 if cycles else 0:.0f} % | {mbs:.2f} | {cpu:,} |")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--program", type=Path, default=HERE / "poll_exp_board.asm")
    parser.add_argument("--port")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    done, errors, rows = read_results(args.program, args.port)
    if not done:
        print("el experimento no ha terminado (exp_done = 0)", file=sys.stderr)
        return 1
    text = f"Fallos de comprobación: {errors}\n\n" + table(rows) + "\n"
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
