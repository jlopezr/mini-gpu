#!/usr/bin/env python3
"""El juego de la vida (examples/asm/race/life.inc), CPU, en C "natural" frente a ensamblador.

    python examples/c/compare_life.py

Una generacion de la rejilla de 160 x 104 con una sopa al azar. Se cuentan las instrucciones de CPU de
`demo_cpu` (ensamblador) y de `life_cpu` (c/race/life.c) y se comprueba que las dos dejan la misma
rejilla siguiente y el mismo framebuffer que el modelo en Python.
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare as base  # noqa: E402
from compare import CpuGpuSystem, assemble_bytes, c_build, first_pass  # noqa: E402

MEMORY = 32 * 1024 * 1024
GRID_A, GRID_B = 0x01060000, 0x01080000
FB = 0x01100000
BLOCK = 0x001F0000
COLS, ROWS, STRIDE = 160, 104, 168
COLOR = 0x07E007E0
RACE = HERE.parent / "asm" / "race"


def soup(seed: int = 7):
    """Rejilla de 106 filas de 168 palabras, borde muerto, ~25 % de vivas."""
    rng = random.Random(seed)
    words = [0] * (106 * STRIDE + 16)       # la ultima celda lee una palabra mas alla de la rejilla
    for y in range(ROWS):
        for x in range(COLS):
            words[(y + 1) * STRIDE + 8 + x] = 1 if rng.random() < 0.25 else 0
    return words


def expected(words):
    at = lambda x, y: words[(y + 1) * STRIDE + 8 + x]  # noqa: E731
    nxt, fb = [0] * len(words), []
    for y in range(ROWS):
        row = []
        for x in range(COLS):
            n = sum(at(x + dx, y + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
            alive = 1 if (n == 3 or (n == 2 and at(x, y))) else 0
            nxt[(y + 1) * STRIDE + 8 + x] = alive
            row.append(COLOR if alive else 0)
        fb += row * 2
    return struct.pack(f"<{len(nxt)}I", *nxt), struct.pack(f"<{len(fb)}I", *fb)


def asm_program():
    source = (f'.include "mmio.inc"\nstart:\n    JAL R31, demo_cpu\n    HALT\n'
              f'.include "{(RACE / "life.inc").as_posix()}"\n')
    image = assemble_bytes(source, RACE, "life_cpu.asm", (base.INC,))
    labels = first_pass(source, RACE, "life_cpu.asm", (base.INC,))[1]
    return image, labels


def c_program(name: str = "life"):
    binary = c_build.build(HERE / "race" / f"{name}.c")
    wrapper = HERE / "_build" / f"{name}.asm"
    labels = first_pass(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                        c_build.INCLUDE_DIRS)[1]
    return binary.read_bytes(), labels


def run(image, block_address, words):
    system = CpuGpuSystem(MEMORY)
    system.load_cpu_program(image)
    system.load_memory(struct.pack(f"<{len(words)}I", *words), GRID_A)
    system.load_memory(struct.pack("<8I", 8, 8, GRID_A, GRID_B, FB, COLOR, 0, 0), block_address)
    system.run()
    size = len(words) * 4
    return (system.cpu.instructions_executed, bytes(system.memory[GRID_B:GRID_B + size]),
            bytes(system.memory[FB:FB + ROWS * 2 * COLS * 4]))


def compare():
    words = soup()
    want_grid, want_fb = expected(words)
    a_image, a_labels = asm_program()
    a = run(a_image, a_labels["job_args"], words)
    ok = lambda r: r[1] == want_grid and r[2] == want_fb  # noqa: E731
    rows = []
    for label, name in (("CPU, C natural (indices)", "life"), ("CPU, C con punteros", "life_ptr")):
        c = run(c_program(name)[0], BLOCK, words)
        rows.append((label, "instrucciones de CPU", a[0], c[0], ok(a) and ok(c)))
    return rows


def main() -> int:
    rows = compare()
    print("| Metodo | Cuenta | Ensamblador | C | C / ens. | Correcto |\n|---|---|---:|---:|---:|---|")
    for name, unit, a, c, ok in rows:
        print(f"| {name} | {unit} | {a:,} | {c:,} | {c / a:.2f} | {'si' if ok else 'NO'} |".replace(".", ","))
    return 0 if all(row[4] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
