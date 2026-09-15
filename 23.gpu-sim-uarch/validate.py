#!/usr/bin/env python3
"""Contrasta el modelo de ciclos contra las cifras medidas en RTL.

Este es el fichero que decide si el modelo sirve para algo. Mientras no
reproduzca el diseño ACTUAL dentro de una tolerancia razonable, cualquier
predicción suya sobre el cauce segmentado es ficción.

Referencia: 22.fpga-gpu-bl8/profiling.md, un frame de examples/plasma.asm con
el scanout encendido, medido con gpu_profile_tb.v sobre el RTL.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "11.gpu-sim-func"))

import minigpu_sim as func  # noqa: E402

from uarch import Config, Model  # noqa: E402


# Medido en RTL con gpu_calib_tb.v sobre examples/plasma_nommio.asm, un frame
# con el scanout encendido.
#
# Se usa la variante SIN MMIO a proposito: plasma.asm lee FB_BACK y escribe
# SWAP, y el simulador funcional no tiene ventana MMIO -- ni debe tenerla. Con
# el programa normal el modelo abortaba con ERROR_MEMORY_ACCESS y acababa
# midiendo un recorrido distinto al del RTL, que es la peor forma de fallar:
# la que produce numeros en vez de un error.
#
# Actualizada tras quitar el fetch redundante de la lane (EXTERNAL_FETCH):
# antes 2_678_274 ciclos, ahora 2_378_037. El resto no cambia, porque es el
# mismo programa haciendo exactamente el mismo trabajo.
REFERENCE = {
    "cycles": 2_378_037,
    "retired": 151_880,
    "lane_ops": 1_214_976,
    "lsu_tx": 9_600,
}

PROGRAM = ROOT / "22.fpga-gpu-bl8" / "examples" / "plasma_nommio.bin"


def build_system(program: Path) -> func.System:
    system = func.System()
    data = program.read_bytes()
    system.memory[0:len(data)] = data
    system.configure_warps({"warps": [{"id": i, "enabled": True, "pc": 0, "active_mask": 0xFF}
                                 for i in range(8)]})
    return system


def patch_fb_back(memory: bytearray, value: int) -> None:
    """Sustituye `LOAD R19, R30, 520` por `MOVHI R19, value>>16`.

    El simulador funcional no tiene ventana MMIO: para él 0x80000208 está fuera
    de la memoria. Como lo único que hace ese LOAD es traerse la base del
    framebuffer, se reemplaza por la constante. Es un parche del BANCO DE
    PRUEBAS, no del programa.
    """
    for offset in range(0, len(memory) - 4, 4):
        instr = struct.unpack_from("<I", memory, offset)[0]
        if instr == 0:
            continue
        opcode = instr >> 26
        rd = (instr >> 21) & 0x1F
        if opcode == 0x15 and rd == 19:                 # LOAD R19, ...
            movhi = (0x17 << 26) | (19 << 21) | ((value >> 16) & 0xFFFF)
            struct.pack_into("<I", memory, offset, movhi)
            return
    raise SystemExit("no encontre el LOAD de FB_BACK que parchear")


def compare(name: str, model: int, reference: int, tolerance: float) -> bool:
    if reference == 0:
        return True
    error = (model - reference) / reference
    ok = abs(error) <= tolerance
    flag = "OK  " if ok else "FAIL"
    print(f"  {flag} {name:<10} modelo {model:>12,}   RTL {reference:>12,}"
          f"   {error*100:>+7.1f} %")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tolerance", type=float, default=0.10,
                        help="error relativo admitido (por defecto 10%%)")
    parser.add_argument("--model", default="baseline", choices=("baseline", "pipelined"))
    parser.add_argument("--exec-base", type=int, default=None)
    args = parser.parse_args()

    if not PROGRAM.exists():
        raise SystemExit(f"falta {PROGRAM}; ensambla plasma_1frame.asm primero")

    system = build_system(PROGRAM)
    cfg = Config(model=args.model)
    if args.exec_base is not None:
        cfg.exec_base = args.exec_base
    counters = Model(system, cfg).run()

    print(counters.report())
    print()

    if args.model != "baseline" or args.exec_base is not None:
        print("  (sin comparar: la referencia RTL es del diseno actual)")
        return 0

    print("=== CONTRA EL RTL ===")
    ok = all([
        compare("cycles", counters.cycles, REFERENCE["cycles"], args.tolerance),
        compare("retired", counters.retired, REFERENCE["retired"], args.tolerance),
        compare("lane_ops", counters.lane_ops, REFERENCE["lane_ops"], args.tolerance),
        compare("lsu_tx", counters.lsu_tx, REFERENCE["lsu_tx"], 0.01),
    ])
    print()
    if ok:
        print("El modelo reproduce el diseno actual: se le puede preguntar por otros.")
        return 0
    print("El modelo NO reproduce el diseno actual. Cualquier prediccion suya")
    print("sobre el cauce segmentado no vale nada hasta arreglar esto.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
