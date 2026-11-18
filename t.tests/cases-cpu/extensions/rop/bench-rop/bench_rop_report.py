#!/usr/bin/env python3
"""Lee y muestra los resultados de bench_rop.asm en la placa 38."""
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


def main() -> int:
    source = HERE / "bench_rop.asm"
    labels = first_pass(source.read_text(encoding="utf-8"), source.parent,
                        source.name, ASM_INCLUDE_DIRS, frozenset({"BOARD"}))[1]
    with tempfile.TemporaryDirectory() as temp:
        data_file = Path(temp) / "result.bin"
        subprocess.run([sys.executable, str(ROOT / "38.fpga-cpu-pipelined" / "monitor.py"),
                        "read-block", str(labels["bench_done"]), "32", str(data_file)], check=True)
        data = data_file.read_bytes()
    done, errors, *cycles = struct.unpack("<8I", data)
    names = ("FILL", "COPY", "SPAN LT Z16/C16")
    print(f"done={done}, errores={errors}")
    print("| Operación | CPU ciclos | ROP ciclos | CPU / ROP |")
    print("|---|---:|---:|---:|")
    for index, name in enumerate(names):
        cpu, rop = cycles[index * 2:index * 2 + 2]
        ratio = cpu / rop if rop else 0
        print(f"| {name} | {cpu:,} | {rop:,} | {ratio:.2f}× |")
    return 0 if done and not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
