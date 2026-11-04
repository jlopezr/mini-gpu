#!/usr/bin/env python3
"""Simulador funcional de MiniGPU para MiniISA v0.1.

Implementa todas las instrucciones actualmente definidas y el estado
arquitectónico de error:

- Sistema: NOP, HALT y la familia GETID (opcode 0x30): GETTID, GETLANE,
  GETWARP, GETLWARP y GETARG. Un `type` mayor que 4 es `ERROR_INVALID_ENCODING`.
- ALU: ADD, SUB, AND, OR, XOR, SHL, SHR y SAR.
- Aritmética: MUL, MULFX y DIV.
- Inmediatas: MOVI, MOVHI, ADDI, ANDI, ORI y XORI.
- Memoria: LOAD y STORE, y los accesos de 8 y 16 bits LOADB, LOADUB, STOREB,
  LOADH, LOADUH y STOREH. Solo a RAM: un acceso sub-palabra a MMIO es error
  (mmio.md §4.1), igual que uno desalineado.
- Control: BEQ, BNE, BLT, BGE, BLTU, BGEU y BRA.
- Llamadas: JAL, JALR y JR, como en la CPU y en la GPU de la 37. JAL salta a un
  destino fijo; JALR y JR lo sacan de un registro por lane, y si las lanes
  activas no coinciden el warp para con ERROR_SIMT: no hay un destino que
  apilar en la pila de divergencia (isa.md, "Disponibilidad").

El estado consta de PC y 32 registros de 32 bits, de los que **R0 está cableado
a cero**: las escrituras se descartan y las lecturas valen siempre cero, igual
que en la MiniCPU y en el RTL de la GPU. Las operaciones hacen wrap módulo
2**32, los binarios son
little-endian y los branches son relativos a PC+4 con offsets expresados en
palabras de 32 bits.

Este modelo utiliza una memoria unificada y byte-addressed de 32 MiB por defecto.
La implementación FPGA, en cambio, tiene espacios Harvard separados de 16 KiB
para programa y datos. Esta diferencia es deliberada: los programas deben evitar
que sus datos se solapen con el código y respetar los límites físicos cuando se
destinen a la FPGA.

El warp controla el PC y contabiliza instrucciones completadas, incluido HALT.
Los errores detienen toda la GPU sin efectos parciales de la instrucción fallida.
Los saltos divergentes utilizan SSY y pilas separadas de regiones y caminos.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
# El modelo está en minigpu_core.py, que también compila el backend Codon.
from minigpu_core import *  # noqa: E402,F401,F403
from gpu_trace import TextTrace, TraceEvent  # noqa: E402,F401


def load_program_file(path: Path) -> bytes:
    """Acepta .asm, .bin o .hex. La logica vive en 1.isa/mini_asm.py para
    que los tres simuladores carguen igual; antes aqui se hacia `read_bytes()`
    a secas y un .asm moria con "el programa debe contener instrucciones
    completas", que es el sintoma (el texto no mide multiplo de 4), no la causa.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1.isa"))
    from mini_asm import load_program_bytes

    return load_program_bytes(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulador funcional de MiniGPU")
    parser.add_argument("program", type=Path, help=".asm, .bin o .hex")
    parser.add_argument("--run-limit", type=int, default=100_000_000,
                        help="límite total de instrucciones de warp completadas")
    parser.add_argument("--memory-size", type=lambda x: int(x, 0), default=32 * 1024 * 1024)
    parser.add_argument("--num-warps", type=int, default=8)
    parser.add_argument("--warp-size", type=int, default=None)
    parser.add_argument("--simt-region-depth", type=int, default=MAX_SIMT_REGIONS,
                        help="capacidad de la pila de regiones por warp (por defecto: 8)")
    parser.add_argument("--simt-path-depth", type=int, default=MAX_SIMT_PATHS,
                        help="capacidad de la pila de caminos por warp (por defecto: 8)")
    parser.add_argument("--config", type=Path, help="JSON con PC, máscara, workgroup_id, logical_warp_id y arg de cada warp")
    parser.add_argument("--dump", nargs=3, metavar=("ADDRESS", "SIZE", "FILE"))
    parser.add_argument("--trace", action="store_true", help="traza del scheduler por instrucción de warp")
    parser.add_argument("--trace-detail", action="store_true", help="incluye registros y memoria por hilo")
    parser.add_argument("--trace-limit", type=int, help="máximo de pasos mostrados; no limita la ejecución")
    parser.add_argument("--trace-file", type=Path, help="guarda la traza en UTF-8 en vez de stderr")
    from tools import sim_peripherals, sim_profile
    sim_peripherals.add_arguments(parser)
    sim_profile.add_arguments(parser)
    args = parser.parse_args()
    try:
        config = None
        if args.config is not None:
            config = json.loads(args.config.read_text(encoding='utf-8-sig'))
            try:
                size = config_warp_size(config)
            except TypeError as exc:
                raise ValueError(str(exc)) from exc
            if args.warp_size is not None and args.warp_size != size:
                raise ValueError("--warp-size no coincide con warp_size de --config")
        else:
            size = args.warp_size if args.warp_size is not None else 8
        system = System(args.memory_size, args.num_warps, size,
                        simt_region_depth=args.simt_region_depth,
                        simt_path_depth=args.simt_path_depth,
                        **sim_peripherals.from_arguments(args))
        system.load_program(load_program_file(args.program), launch=args.config is None)
        if args.config is not None:
            try:
                system.configure_warps(config)
            except TypeError as exc:
                raise ValueError(str(exc)) from exc
        profile = sim_profile.from_arguments(args)
        sim_peripherals.start_display(system)
        tracing = args.trace or args.trace_detail or args.trace_file is not None or args.trace_limit is not None
        if args.trace_limit is not None and args.trace_limit < 0:
            raise ValueError('trace-limit no puede ser negativo')
        if tracing:
            if args.trace_file is not None:
                protected = [args.program, args.config]
                if args.dump:
                    protected.append(Path(args.dump[2]))
                if any(path is not None and path.resolve() == args.trace_file.resolve() for path in protected):
                    raise ValueError('trace-file debe ser distinto del programa, configuración y dump')
            output = args.trace_file.open('w', encoding='utf-8') if args.trace_file else nullcontext(sys.stderr)
            with output as stream:
                text = TextTrace(stream, detail=args.trace_detail, limit=args.trace_limit)
                system.trace = text if profile is None else sim_profile.GpuEvents(profile, lambda: text)
                try:
                    system.run(args.run_limit)
                except SimulationError as exc:
                    system.trace.finish(f'SIMULADOR: {exc}')
                    raise
                else:
                    system.trace.finish(f'{system.fault or "HALT"}; '
                                        f'{system.instructions_executed} instrucciones de warp')
                finally:
                    system.trace = None
        else:
            if profile is not None:
                system.trace = sim_profile.GpuEvents(profile)
            system.run(args.run_limit)
            system.trace = None
        sim_peripherals.write_outputs(args, system)
        if system.fault:
            fault = system.fault
            print(f"ERROR 0x{fault.code:02X} en PC=0x{fault.pc:08X}, "
                  f"warp={fault.warp_id}, hilo={fault.core_id}, "
                  f"dirección={fault.address}; "
                  f"{system.instructions_executed} instrucciones de warp", file=sys.stderr)
        else:
            print(f"HALT tras {system.instructions_executed} instrucciones de warp")
        if args.dump:
            address, size, filename = args.dump
            system.dump_memory(int(address, 0), int(size, 0), Path(filename))
        sim_profile.write_report(args, profile)
        sys.stdout.flush()
        sim_peripherals.finish_display(system)
        return 1 if system.error else 0
    except (OSError, ValueError, SimulationError) as exc:
        print(f"Simulador: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
