#!/usr/bin/env python3
"""La rotacion de textura (examples/asm/race/rotate.inc) en C frente a ensamblador, en los tres metodos.

    python examples/c/system/compare_rotate.py [--frame 5]

CPU, GPU inocente (un hilo por fila) y GPU buena (un warp por fila), cada uno en C
(c/race/rotate.c) y en ensamblador (rotate.inc). Las dos GPU se lanzan sin programa de CPU, con los
mismos datos que gpu_run (descriptores y WARP_START); la CPU se ejecuta hasta HALT. Se cuentan
instrucciones (de CPU, o de warp) y se comprueba que cada una deja la imagen del modelo en Python.
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare as base  # noqa: E402
from compare import CpuGpuSystem, assemble_bytes, c_build, first_pass, launch  # noqa: E402

MEMORY = 32 * 1024 * 1024
ROT_TEX = 0x010A0000
FB = 0x01100000
BLOCK = 0x001F0000
ROWS, COLS = 104, 160
WARPS = 8
RACE = HERE.parents[1] / "asm" / "race"


def texture():
    out = []
    for ty in range(128):
        for tx in range(128):
            if ((tx >> 4) ^ (ty >> 4)) & 1:
                red = tx >> 2
                color = red << 11 | (ty >> 1) << 5 | (31 - red)
            else:
                color = 0x18C3
            out.append(color | color << 16)
    return out


def parameters(frame: int):
    sin = [int(round(128 * math.sin(2 * math.pi * k / 64))) for k in range(64)]
    a = abs((frame & 31) - 16) - 8
    s = 48 + abs(((frame * 3) & 63) - 32)
    dux = (sin[(a + 16) & 63] * s) >> 7
    dvx = (sin[a & 63] * s) >> 7
    return (8192 + 40 * frame - 80 * dux + 52 * dvx, 8192 + 24 * frame - 80 * dvx - 52 * dux, dux, dvx)


def expected(frame: int, tex) -> bytes:
    u00, v00, dux, dvx = parameters(frame)
    out = bytearray()
    for y in range(ROWS):
        u, v = u00 - y * dvx, v00 + y * dux
        row = []
        for _ in range(COLS):
            row.append(tex[(v & 0x3F80) + ((u >> 7) & 127)])
            u += dux
            v += dvx
        out += struct.pack("<160I", *row) * 2
    return bytes(out)


def asm_program():
    source = (f'.include "mmio.inc"\nstart:\n    JAL R31, demo_cpu\n    HALT\n'
              f'.include "{(RACE / "rotate.inc").as_posix()}"\n')
    image = assemble_bytes(source, RACE, "rotate_cpu.asm", (base.INC,))
    labels = first_pass(source, RACE, "rotate_cpu.asm", (base.INC,))[1]
    return image, labels


def c_program():
    binary = c_build.build(HERE.parent / "race" / "rotate.c")
    wrapper = HERE.parent / "_build" / "rotate.asm"
    labels = first_pass(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                        c_build.INCLUDE_DIRS)[1]
    return binary.read_bytes(), labels


def prepare(image, frame, tex, block_address):
    system = CpuGpuSystem(MEMORY)
    system.load_cpu_program(image)
    system.load_memory(struct.pack("<16384I", *tex), ROT_TEX)
    u00, v00, dux, dvx = parameters(frame)
    system.load_memory(struct.pack("<8I", WARPS, 8, FB, u00 & 0xFFFFFFFF, v00 & 0xFFFFFFFF,
                                   dux & 0xFFFFFFFF, dvx & 0xFFFFFFFF, 0), block_address)
    return system


def run_cpu(image, block_address, frame, tex):
    system = prepare(image, frame, tex, block_address)
    system.run()
    return system.cpu.instructions_executed, bytes(system.memory[FB:FB + ROWS * 2 * COLS * 4])


def run_gpu(image, entry, frame, tex):
    system = prepare(image, frame, tex, BLOCK)
    launch(system, entry, WARPS, BLOCK)
    return system.gpu.retired, bytes(system.memory[FB:FB + ROWS * 2 * COLS * 4])


def compare(frame: int = 5):
    tex = texture()
    want = expected(frame, tex)
    a_image, a_labels = asm_program()
    c_image, c_labels = c_program()
    rows = []
    a_count, a_memory = run_cpu(a_image, a_labels["job_args"], frame, tex)
    c_count, c_memory = run_cpu(c_image, BLOCK, frame, tex)
    rows.append(("CPU", "instrucciones de CPU", a_count, c_count, a_memory == want and c_memory == want))
    for name, a_entry, c_entry in (("GPU inocente", "rot_k_naive", "__kernel_rot_naive"),
                                   ("GPU buena", "rot_k_good", "__kernel_rot_good")):
        a_count, a_memory = run_gpu(a_image, a_labels[a_entry], frame, tex)
        c_count, c_memory = run_gpu(c_image, c_labels[c_entry], frame, tex)
        rows.append((name, "instrucciones de warp", a_count, c_count, a_memory == want and c_memory == want))
    return rows


def table(rows) -> str:
    out = ["| Metodo | Cuenta | Ensamblador | C | C / ens. | Correcto |", "|---|---|---:|---:|---:|---|"]
    for name, unit, a, c, ok in rows:
        out.append(f"| {name} | {unit} | {a:,} | {c:,} | {c / a:.2f} | {'si' if ok else 'NO'} |".replace(".", ","))
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frame", type=int, default=5)
    args = parser.parse_args()
    rows = compare(args.frame)
    print(table(rows))
    return 0 if all(row[4] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
