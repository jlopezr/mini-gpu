#!/usr/bin/env python3
"""Compara en el simulador los kernels de sistema en C (dma/gpu_kernels.c) con los de ensamblador.

    python examples/c/system/compare.py [--out tabla.md]

Cada kernel se lanza sin programa de CPU: se escriben los descriptores de los warps y
WARP_START por MMIO (lo mismo que gpu_run) y se cuentan las instrucciones de warp que retira
la GPU (`gpu.retired`). Los dos juegos de kernels leen el mismo bloque de argumentos, asi
que se lanzan con exactamente los mismos datos, y se comprueba que dejan la misma memoria.
"""
from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parents[2]
ROOT = HERE.parents[3]
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(HERE))

import build as c_build  # noqa: E402
import cpu_gpu_sim as sim  # noqa: E402
from cpu_gpu_sim import CpuGpuSystem, mm  # noqa: E402
from mini_asm import assemble_bytes, first_pass  # noqa: E402

MEMORY = 1 << 21
SRC, DST, BLOCK = 0x100000, 0x140000, 0x1F0000
INC = ROOT / "x.tests" / "inc"
LANES = 8


@dataclass
class Workload:
    name: str
    kernel: str                 # memset | memcpy | fill_rect | blit
    nwarps: int
    params: tuple
    elements: int               # palabras que escribe


WORKLOADS = [
    Workload("memset 4096", "memset", 4, (DST, 0xABCD1234, 4096), 4096),
    Workload("memcpy 4096", "memcpy", 4, (DST, SRC, 4096), 4096),
    Workload("fill_rect 64x64", "fill_rect", 4, (DST, 320, 64, 64, 0xAAAA5555), 64 * 64),
    Workload("blit 64x64", "blit", 4, (DST, 320, SRC, 288, 64, 64), 64 * 64),
    Workload("fill_rect 7x13 (3 warps)", "fill_rect", 3, (DST, 96, 13, 7, 0xAAAA5555), 7 * 13),
    Workload("blit 7x13 (5 warps)", "blit", 5, (DST, 112, SRC, 60, 13, 7), 7 * 13),
]


def asm_image():
    source = '.include "mmio.inc"\n.include "gpu_kernels.inc"\n'
    folder = HERE.parents[1] / "asm" / "dma"
    image = assemble_bytes(source, folder, "kernels.asm", (INC,))
    labels = first_pass(source, folder, "kernels.asm", (INC,))[1]
    return image, {k: labels[f"gpu_k_{k}"] for k in ("memset", "memcpy", "fill_rect", "blit")}


def c_image():
    binary = c_build.build(HERE.parent / "dma" / "gpu_kernels.c")
    wrapper = HERE.parent / "_build" / "gpu_kernels.asm"
    labels = first_pass(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                        c_build.INCLUDE_DIRS)[1]
    return binary.read_bytes(), {k: labels[f"__kernel_{k}"] for k in ("memset", "memcpy", "fill_rect", "blit")}


def write(system, address, value):
    port = system.bus.device_for("cpu", address)
    port.write(address - port.BASE, value)


def launch(system, pc, nwarps, block):
    """Lo mismo que gpu_run: descriptores, argumentos y WARP_START."""
    for w in range(nwarps):
        base = mm.MMIO_GPU_WARPS_BASE + w * mm.MMIO_GPU_WARPS_STRIDE
        write(system, base + mm.MMIO_GPU_WARPS_PC_OFF, pc)
        write(system, base + mm.MMIO_GPU_WARPS_ACTIVE_OFF, (1 << LANES) - 1)
        write(system, base + mm.MMIO_GPU_WARPS_GROUP_OFF, 1)
        arrays = mm.MMIO_GPU_WARPS_BASE + w * 4
        write(system, arrays + mm.MMIO_GPU_WARPS_LOGICAL_ID_OFF, w)
        write(system, arrays + mm.MMIO_GPU_WARPS_ARG_OFF, block)
    write(system, mm.MMIO_GPU_BASE + mm.MMIO_GPU_WARP_START_OFF, (1 << nwarps) - 1)
    for _ in range(5_000_000):
        if system.gpu.system.halted:
            return
        system.gpu.step()
    raise RuntimeError("la GPU no paro")


def pattern(count, seed):
    return [(seed + 0x9E3779B1 * n) & 0xFFFFFFFF for n in range(count)]


def run_one(image, entry, work: Workload):
    """Instrucciones de warp y memoria resultante (DST y los 64 KiB que lo rodean)."""
    system = CpuGpuSystem(MEMORY)
    system.load_cpu_program(image)
    system.load_memory(struct.pack("<16384I", *pattern(16384, 7)), SRC)
    system.load_memory(struct.pack("<16384I", *([0x5A5A5A5A] * 16384)), DST)     # guarda
    block = struct.pack("<8I", work.nwarps, LANES, *(list(work.params) + [0] * 6)[:6])
    system.load_memory(block, BLOCK)
    launch(system, entry, work.nwarps, BLOCK)
    return system.gpu.retired, bytes(system.memory[DST:DST + 65536])


def compare():
    asm_code, asm_entries = asm_image()
    c_code, c_entries = c_image()
    rows = []
    for work in WORKLOADS:
        a_count, a_memory = run_one(asm_code, asm_entries[work.kernel], work)
        c_count, c_memory = run_one(c_code, c_entries[work.kernel], work)
        rows.append((work, a_count, c_count, a_memory == c_memory, a_memory))
    return rows


def table(rows) -> str:
    out = ["| Carga | Elementos | Ensamblador | C | C / ens. | Instr. por elemento (ens.) | (C) |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for work, a, c, _, _ in rows:
        out.append(f"| {work.name} | {work.elements} | {a:,} | {c:,} | {c / a:.2f} "
                   f"| {a / work.elements:.2f} | {c / work.elements:.2f} |".replace(".", ","))
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = compare()
    text = table(rows)
    print(text)
    for work, _, _, same, _ in rows:
        if not same:
            print(f"AVISO: {work.name}: la memoria resultante difiere entre C y ensamblador", file=sys.stderr)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0 if all(same for _, _, _, same, _ in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
