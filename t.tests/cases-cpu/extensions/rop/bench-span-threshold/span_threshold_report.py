#!/usr/bin/env python3
"""Lee la curva de rentabilidad de span_threshold.asm en la placa 38."""
from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "1.isa"))
from mini_asm import first_pass  # noqa: E402
from runtime_dirs import ASM_INCLUDE_DIRS  # noqa: E402

ROWS = 64


def main() -> int:
    source = HERE / "span_threshold.asm"
    labels = first_pass(source.read_text(encoding="utf-8"), source.parent,
                        source.name, ASM_INCLUDE_DIRS, frozenset({"BOARD"}))[1]
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "result.bin"
        subprocess.run([sys.executable, str(ROOT / "38.fpga-cpu-pipelined" / "monitor.py"),
                        "read-block", str(labels["done"]), "192", str(output)], check=True)
        data = output.read_bytes()
    done, errors = struct.unpack_from("<2I", data)
    widths = struct.unpack_from("<15I", data, labels["widths"] - labels["done"])
    cycles = struct.unpack_from("<30I", data, labels["results"] - labels["done"])
    print(f"done={done}, errores={errors}; {ROWS} spans por muestra (CONFIG incluido)")
    print("| Ancho | CPU ciclos/span | ROP ciclos/span | CPU / ROP | Gana |")
    print("|---:|---:|---:|---:|:---|")
    for width, cpu, rop in zip(widths, cycles[::2], cycles[1::2]):
        cpu_span, rop_span = cpu / ROWS, rop / ROWS
        winner = "ROP" if rop < cpu else "CPU"
        ratio = cpu / rop if rop else 0
        print(f"| {width} | {cpu_span:.1f} | {rop_span:.1f} | {ratio:.2f}x | {winner} |")
    return 0 if done and not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
