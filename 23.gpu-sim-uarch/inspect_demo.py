#!/usr/bin/env python3
"""Enseña qué estado se puede mirar después de una ejecución, y cuál no.

El modelo de ciclos no ejecuta la ISA: se la delega al simulador funcional de
`11.gpu-sim-func`. La consecuencia práctica es que el estado ARQUITECTONICO
—registros, memoria, PC, mascaras— es real y se puede inspeccionar.

Lo que NO hay es estado MICROARQUITECTONICO: `uarch.Model` es un modelo de
COSTE, no estructural. No existen registros de etapa que mirar porque no hay
etapas; el bucle calcula cuándo acaba cada instrucción y avanza el reloj.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "11.gpu-sim-func"))

import minigpu_sim as func  # noqa: E402

from uarch import Config, Model  # noqa: E402


def main() -> int:
    program = ROOT / "22.fpga-gpu-bl8" / "examples" / "vector.bin"
    if not program.exists():
        raise SystemExit(f"falta {program}")

    system = func.System()
    data = program.read_bytes()
    system.memory[0:len(data)] = data
    system.configure_warps({"warps": [{"id": i, "enabled": True, "pc": 0,
                                       "active_mask": 0xFF} for i in range(8)]})

    counters = Model(system, Config()).run()
    print(f"ciclos={counters.cycles}  instrucciones={counters.retired}"
          f"  CPI={counters.cycles / counters.retired:.2f}")
    print()

    sm = system.streaming_multiprocessor
    print("--- estado arquitectonico: SI se puede mirar ---")
    for warp_id in (0, 3, 7):
        warp = sm.warps[warp_id]
        r1 = [warp.processors[l].regs[1] for l in range(8)]   # GETTID
        r5 = [warp.processors[l].regs[5] for l in range(8)]   # el LOAD
        print(f"  warp {warp_id}  pc=0x{warp.pc:04x}  mascara=0x{warp.active_mask:02x}")
        print(f"    R1 (tid) = {r1}")
        print(f"    R5 (load)= {[hex(v) for v in r5]}")

    print()
    words = [struct.unpack_from('<I', system.memory, 4096 + i * 4)[0] for i in range(8)]
    print(f"  memoria en 4096: {[hex(w) for w in words]}")

    print()
    print("--- estado microarquitectonico: NO lo hay ---")
    print("  El modelo calcula CUANDO acaba cada instruccion, no QUE hay en la")
    print("  etapa D en el ciclo 12345. No existen registros de etapa que mirar.")
    print("  Lo unico temporal que guarda es:")
    print("    busy_until[warp]  cuando vuelve a estar libre cada warp")
    print("    exec_free_at      cuando se libera la etapa de ejecucion")
    print("    mem.busy_until    cuando se libera el canal de memoria")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
