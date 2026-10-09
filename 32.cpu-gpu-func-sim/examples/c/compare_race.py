#!/usr/bin/env python3
"""Las cargas de `race` (rotacion, vida, difusion de calor) en C frente a ensamblador, en los tres metodos.

    python examples/c/compare_race.py [rotate|life|blur|all] [--frame 5]

CPU, GPU inocente (un hilo por fila) y GPU buena (un warp por fila), cada uno en C (c/race/<carga>.c) y en
ensamblador (asm/race/<carga>.inc). Las dos GPU se lanzan sin programa de CPU, con los mismos datos que
gpu_run (descriptores y WARP_START); la CPU se ejecuta hasta HALT. Se cuentan instrucciones (de CPU, o de
warp) y se comprueba que cada version deja las salidas del modelo en Python.

Una carga es un `Workload`: sus ficheros, los nombres de sus kernels y una funcion que da los datos de
entrada (`Case`: memoria, bloque de argumentos y lo que hay que leer al terminar con su valor esperado).
Para anadir una, un `Workload` en WORKLOADS. El cubo (compare_cube.py) corre el demo entero y es otro caso.
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare as base  # noqa: E402
from compare import CpuGpuSystem, assemble_bytes, c_build, first_pass, launch  # noqa: E402

MEMORY = 32 * 1024 * 1024
BLOCK = 0x001F0000          # donde se deja el bloque para la GPU y para la CPU en C
WARPS = 8
RACE = HERE.parent / "asm" / "race"
GRID_A, GRID_B, FB = 0x01060000, 0x01080000, 0x01100000
COLS, ROWS, STRIDE = 160, 104, 168


@dataclass
class Case:
    """Los datos de una ejecucion: `memory` [(direccion, bytes)], el bloque de argumentos (palabras, tras
    nwarps y nlanes) y las zonas a comprobar [(direccion, bytes esperados)]."""
    memory: list[tuple[int, bytes]]
    block: tuple[int, ...]
    expect: list[tuple[int, bytes]]


@dataclass
class Workload:
    name: str
    stem: str                                       # c/race/<stem>.c y asm/race/<stem>.inc
    asm_kernels: tuple[str, str]                    # etiquetas de la inocente y la buena en el .inc
    c_kernels: tuple[str, str]
    case: Callable[[int], Case]                     # el parametro (fotograma, semilla...)
    default: int = 0
    extra_cpu: tuple[tuple[str, str], ...] = ()     # (nombre de la fila, fuente C) de otras formas de escribir la CPU
    asm_block_label: str = "job_args"               # donde el .inc espera el bloque en la CPU


# ---- rotacion de textura ----
ROT_TEX = 0x010A0000


def rotate_case(frame: int) -> Case:
    texture = []
    for ty in range(128):
        for tx in range(128):
            if ((tx >> 4) ^ (ty >> 4)) & 1:
                red = tx >> 2
                color = red << 11 | (ty >> 1) << 5 | (31 - red)
            else:
                color = 0x18C3
            texture.append(color | color << 16)
    sin = [int(round(128 * math.sin(2 * math.pi * k / 64))) for k in range(64)]
    a = abs((frame & 31) - 16) - 8
    s = 48 + abs(((frame * 3) & 63) - 32)
    dux = (sin[(a + 16) & 63] * s) >> 7
    dvx = (sin[a & 63] * s) >> 7
    u00, v00 = 8192 + 40 * frame - 80 * dux + 52 * dvx, 8192 + 24 * frame - 80 * dvx - 52 * dux
    image = bytearray()
    for y in range(ROWS):
        u, v = u00 - y * dvx, v00 + y * dux
        row = []
        for _ in range(COLS):
            row.append(texture[(v & 0x3F80) + ((u >> 7) & 127)])
            u += dux
            v += dvx
        image += struct.pack("<160I", *row) * 2
    mask = 0xFFFFFFFF
    return Case([(ROT_TEX, struct.pack("<16384I", *texture))],
                (FB, u00 & mask, v00 & mask, dux & mask, dvx & mask, 0), [(FB, bytes(image))])


# ---- juego de la vida y difusion de calor: la misma rejilla ----
def grid_words(value: Callable[[random.Random], int], seed: int) -> list[int]:
    """106 filas de 168 palabras con borde muerto (y una mas, que la ultima celda lee)."""
    rng = random.Random(seed)
    words = [0] * (106 * STRIDE + 16)
    for y in range(ROWS):
        for x in range(COLS):
            words[(y + 1) * STRIDE + 8 + x] = value(rng)
    return words


def grid_case(words: list[int], step: Callable[[Callable[[int, int], int], int, int], tuple[int, int]],
              color: int) -> Case:
    at = lambda x, y: words[(y + 1) * STRIDE + 8 + x]  # noqa: E731
    nxt, fb = [0] * len(words), []
    for y in range(ROWS):
        row = []
        for x in range(COLS):
            value, pixel = step(at, x, y)
            nxt[(y + 1) * STRIDE + 8 + x] = value
            row.append(pixel)
        fb += row * 2
    return Case([(GRID_A, struct.pack(f"<{len(words)}I", *words))],
                (GRID_A, GRID_B, FB, color, 0, 0),
                [(GRID_B, struct.pack(f"<{len(nxt)}I", *nxt)), (FB, struct.pack(f"<{len(fb)}I", *fb))])


LIFE_COLOR = 0x07E007E0


def life_case(seed: int) -> Case:
    def step(at, x, y):
        n = sum(at(x + dx, y + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
        alive = 1 if (n == 3 or (n == 2 and at(x, y))) else 0
        return alive, LIFE_COLOR if alive else 0
    return grid_case(grid_words(lambda rng: 1 if rng.random() < 0.25 else 0, seed), step, LIFE_COLOR)


def blur_case(seed: int) -> Case:
    def step(at, x, y):
        total = (4 * at(x, y) + 2 * (at(x, y - 1) + at(x, y + 1) + at(x - 1, y) + at(x + 1, y))
                 + at(x - 1, y - 1) + at(x + 1, y - 1) + at(x - 1, y + 1) + at(x + 1, y + 1))
        value = (total * 15) >> 8
        pixel = ((value << 8) & 0xF800) | ((value << 3) & 0x07E0)
        return value, pixel | pixel << 16
    return grid_case(grid_words(lambda rng: rng.randrange(256) if rng.random() < 0.5 else 0, seed), step, 0)


WORKLOADS = {w.name: w for w in (
    Workload("rotate", "rotate", ("rot_k_naive", "rot_k_good"), ("__kernel_rot_naive", "__kernel_rot_good"),
             rotate_case, default=5),
    Workload("life", "life", ("life_k_naive", "life_k_good"), ("__kernel_life_naive", "__kernel_life_good"),
             life_case, default=7, extra_cpu=(("CPU, C con punteros", "life_ptr"),)),
    Workload("blur", "blur", ("blur_k_naive", "blur_k_good"), ("__kernel_blur_naive", "__kernel_blur_good"),
             blur_case, default=11),
)}


def asm_program(work: Workload):
    source = (f'.include "mmio.inc"\nstart:\n    JAL R31, demo_cpu\n    HALT\n'
              f'.include "{(RACE / (work.stem + ".inc")).as_posix()}"\n')
    name = f"{work.stem}_cpu.asm"
    return assemble_bytes(source, RACE, name, (base.INC,)), first_pass(source, RACE, name, (base.INC,))[1]


def c_program(stem: str):
    binary = c_build.build(HERE / "race" / f"{stem}.c")
    wrapper = HERE / "_build" / f"{stem}.asm"
    labels = first_pass(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name, c_build.INCLUDE_DIRS)[1]
    return binary.read_bytes(), labels


def prepare(image, case: Case, block_address: int):
    system = CpuGpuSystem(MEMORY)
    system.load_cpu_program(image)
    for address, data in case.memory:
        system.load_memory(data, address)
    system.load_memory(struct.pack(f"<{2 + len(case.block)}I", WARPS, 8, *case.block), block_address)
    return system


def correct(system, case: Case) -> bool:
    return all(bytes(system.memory[address:address + len(data)]) == data for address, data in case.expect)


def run_cpu(image, block_address: int, case: Case):
    system = prepare(image, case, block_address)
    system.run()
    return system.cpu.instructions_executed, correct(system, case)


def run_gpu(image, entry: int, case: Case):
    system = prepare(image, case, BLOCK)
    launch(system, entry, WARPS, BLOCK)
    return system.gpu.retired, correct(system, case)


def compare(name: str, parameter: int | None = None):
    """[(metodo, cuenta, ensamblador, C, correcto)] de la carga `name`."""
    work = WORKLOADS[name]
    case = work.case(work.default if parameter is None else parameter)
    a_image, a_labels = asm_program(work)
    c_image, c_labels = c_program(work.stem)
    a_count, a_ok = run_cpu(a_image, a_labels[work.asm_block_label], case)
    rows = []
    for label, stem in (("CPU", work.stem), *work.extra_cpu):
        c_count, c_ok = run_cpu(c_image if stem == work.stem else c_program(stem)[0], BLOCK, case)
        rows.append((label, "instrucciones de CPU", a_count, c_count, a_ok and c_ok))
    for label, a_entry, c_entry in (("GPU inocente", work.asm_kernels[0], work.c_kernels[0]),
                                    ("GPU buena", work.asm_kernels[1], work.c_kernels[1])):
        a_count, a_ok = run_gpu(a_image, a_labels[a_entry], case)
        c_count, c_ok = run_gpu(c_image, c_labels[c_entry], case)
        rows.append((label, "instrucciones de warp", a_count, c_count, a_ok and c_ok))
    return rows


def table(rows) -> str:
    out = ["| Metodo | Cuenta | Ensamblador | C | C / ens. | Correcto |", "|---|---|---:|---:|---:|---|"]
    for name, unit, a, c, ok in rows:
        out.append(f"| {name} | {unit} | {a:,} | {c:,} | {c / a:.2f} | {'si' if ok else 'NO'} |".replace(".", ","))
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workload", nargs="?", default="all", choices=[*WORKLOADS, "all"])
    parser.add_argument("--frame", type=int, help="el parametro de la carga (fotograma de la rotacion, semilla de la rejilla)")
    args = parser.parse_args()
    ok = True
    for name in (WORKLOADS if args.workload == "all" else [args.workload]):
        rows = compare(name, args.frame)
        print(f"### {name}\n\n{table(rows)}")
        ok = ok and all(row[4] for row in rows)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
