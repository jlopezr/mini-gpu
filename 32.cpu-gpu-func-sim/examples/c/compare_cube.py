#!/usr/bin/env python3
"""El cubo (examples/asm/race/cube.asm) en C frente a ensamblador, en los tres metodos.

    python examples/c/compare_cube.py [--frames 6]

Se ejecuta el demo completo (anfitrion de video, doble buffer) con `race_period = 1`, asi que cada
fotograma usa un metodo distinto: CPU, GPU inocente y GPU buena, por turno. Entre dos cambios de buffer
se cuentan las instrucciones de CPU y de warp; de cada metodo se da la que hace el trabajo (CPU para el
metodo de CPU, warp para los dos de GPU: la CPU de esos solo espera). Se mide el segundo giro de los
tres metodos (fotogramas 3 a 5), no el primero, que lleva el arranque del demo. Se comprueba ademas que
C y ensamblador dejan la misma imagen en pantalla.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare as base  # noqa: E402
from compare import CpuGpuSystem, assemble_bytes, c_build, first_pass  # noqa: E402
import cpu_gpu_sim as sim  # noqa: E402
import struct  # noqa: E402

RACE = HERE.parent / "asm" / "race"
METHODS = (("CPU", "instrucciones de CPU"), ("GPU inocente", "instrucciones de warp"),
           ("GPU buena", "instrucciones de warp"))
MEMORY = 32 * 1024 * 1024


def asm_program():
    path = RACE / "cube.asm"
    source = path.read_text(encoding="utf-8")
    labels = first_pass(source, RACE, path.name, (base.INC,))[1]
    return assemble_bytes(source, RACE, path.name, (base.INC,)), labels


def c_program():
    binary = c_build.build(HERE / "race" / "cube.c")
    wrapper = HERE / "_build" / "cube.asm"
    labels = first_pass(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                        c_build.INCLUDE_DIRS)[1]
    return binary.read_bytes(), labels


def run(image, labels, frames: int):
    """([(CPU, warp) por fotograma], pantalla visible al terminar)."""
    video = sim.VideoDevice(frame_instructions=1000)
    video.stop_after_swaps = frames
    system = CpuGpuSystem(MEMORY, video=video)
    system.load_cpu_program(image)
    system.load_memory(struct.pack("<I", 1), labels["race_period"])
    counts, swaps, last = [], 0, (0, 0)
    while not system.finished:
        system.step_round()
        if video.swap_count != swaps:
            swaps = video.swap_count
            now = (system.cpu.instructions_executed, system.gpu.retired)
            counts.append((now[0] - last[0], now[1] - last[1]))
            last = now
    start = video.fb_front + 32 * 640
    return counts, bytes(system.memory[start:start + 208 * 640])


def compare(frames: int = 6):
    """Un giro de tres metodos por cada tres fotogramas; el primero se descarta, porque el fotograma 0
    lleva el arranque del demo (generar las texturas, unas 500.000 a 650.000 instrucciones de CPU que no
    son del metodo) y falsearia el de CPU."""
    a_counts, a_screen = run(*asm_program(), frames)
    c_counts, c_screen = run(*c_program(), frames)
    rows = []
    for index, (name, unit) in enumerate(METHODS):
        column = 0 if index == 0 else 1
        a = sum(frame[column] for frame in a_counts[3 + index::3])
        c = sum(frame[column] for frame in c_counts[3 + index::3])
        rows.append((name, unit, a, c, a_screen == c_screen))
    return rows


def table(rows) -> str:
    out = ["| Metodo | Cuenta | Ensamblador | C | C / ens. | Misma imagen |", "|---|---|---:|---:|---:|---|"]
    for name, unit, a, c, ok in rows:
        out.append(f"| {name} | {unit} | {a:,} | {c:,} | {c / a:.2f} | {'si' if ok else 'NO'} |".replace(".", ","))
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=int, default=6,
                        help="multiplo de 3, al menos 6 (por defecto 6: se mide el segundo giro de metodos)")
    args = parser.parse_args()
    rows = compare(args.frames)
    print(table(rows))
    return 0 if all(row[4] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
