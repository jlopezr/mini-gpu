#!/usr/bin/env python3
"""Simulador funcional de MiniCPU + MiniGPU sobre una RAM compartida.

No reimplementa ningún núcleo: importa `CPU` de `2.cpu-sim-func` y `System` de
`11.gpu-sim-func` y les pone en medio lo que les falta para convivir —una sola
RAM y un bus MMIO v2 con el mapa y los permisos de `1.isa/mmio.md`—.

Qué se comparte
---------------
- La RAM: **el mismo `bytearray`** en la CPU y en todas las lanes de la GPU. Lo
  que escribe uno lo lee el otro sin copias ni caché (§18: el modelo funcional
  hace visible cada escritura al retirarse la instrucción).
- SYSTEM, SERIAL, VIDEO e INPUT: los mismos objetos de `tools/sim_devices.py`,
  accesibles desde las dos (§15). El reloj sintético de los dispositivos avanza
  una vez por instrucción retirada, sea de la CPU o de un warp.

Dónde se sincronizan
--------------------
Solo en el MMIO de la GPU (§14), que es lo que hace el hardware:

- La CPU escribe los descriptores en `GPU WARPS` y lanza con
  `GPU_CONTROL.RUN` o `WARP_START`.
- La CPU sondea `GPU_STATUS`, `WARP_LIVE` y `WARP_DONE`. `WARP_DONE` es pegajoso
  y se limpia escribiendo unos (W1C).

No hay ningún otro canal: ni hilos, ni callbacks, ni estado compartido fuera de
la RAM y de esos registros.

Planificación
-------------
Determinista y de un solo hilo: cada ronda ejecuta `cpu_steps` instrucciones de
CPU y luego `gpu_steps` instrucciones de warp (un warp por instrucción, el
round-robin de `11`). Con la misma entrada el resultado se repite siempre, pero
el reparto de velocidades es una elección del modelo, no una medida: el
simulador cuenta instrucciones, no ciclos ni esperas.

Qué no hace (aún)
-----------------
CPU PERFORMANCE, GPU PERFORMANCE, CPU DEBUG, TIMER, INTC, DMA, FABRIC y SDRAM no
existen: acceder a ellos es error, no cero (§17). La regla de §4.2 —una sola
lane activa en un acceso MMIO desde SIMT— tampoco la comprueba `11`.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, Path(__file__).resolve().parent, ROOT / "2.cpu-sim-func",
                ROOT / "11.gpu-sim-func", ROOT / "1.isa" / "asm2"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

# El modelo está en cpu_gpu_core.py, que también compila el backend Codon.
from cpu_gpu_core import *  # noqa: E402,F401,F403
import minicpu_sim as cpu_sim  # noqa: E402
import minigpu_sim as gpu_sim  # noqa: E402
from tools import sim_peripherals  # noqa: E402
from tools import sim_profile  # noqa: E402


def load_program_file(path: Path) -> bytes:
    return cpu_sim.load_program_file(path)


def _hex(value: str) -> int:
    return int(value, 0)


def parse_arguments(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Simulador funcional de MiniCPU + MiniGPU sobre una RAM compartida")
    parser.add_argument("--backend", choices=("python", "codon"), default="python",
                        help="motor de ejecución (python por defecto; codon es opcional)")
    parser.add_argument("program", type=Path,
                        help=".asm, .bin o .hex con el programa de la CPU y el kernel "
                             "de la GPU en una sola imagen, cargada en 0")
    parser.add_argument("--run-limit", type=int, default=100_000_000,
                        help="límite de instrucciones de CPU y de warp: N para cada "
                             "uno, no N entre los dos (100000000)")
    parser.add_argument("--cpu-run-limit", type=int,
                        help="sustituye --run-limit solo para la CPU")
    parser.add_argument("--gpu-run-limit", type=int,
                        help="sustituye --run-limit solo para los warps")
    parser.add_argument("--memory-size", type=_hex, default=32 * 1024 * 1024)
    parser.add_argument("--num-warps", type=int, default=8)
    parser.add_argument("--warp-size", type=int, default=8)
    parser.add_argument("--cpu-steps", type=int, default=1,
                        help="instrucciones de CPU por ronda (1)")
    parser.add_argument("--gpu-steps", type=int, default=1,
                        help="instrucciones de warp por ronda (1)")
    parser.add_argument("--dump", nargs=3, metavar=("ADDRESS", "SIZE", "FILE"))
    parser.add_argument("--trace", action="store_true",
                        help="traza intercalada CPU/warp por instrucción, a stderr")
    parser.add_argument("--trace-limit", type=int,
                        help="máximo de líneas de traza, de CPU y de warp juntas; implica "
                             "--trace y no limita la ejecución")
    parser.add_argument("--trace-file", type=Path,
                        help="como --trace, pero en un fichero UTF-8")
    sim_peripherals.add_arguments(parser)
    sim_profile.add_arguments(parser)
    return parser.parse_args(argv)


#: Una GPU con warps vivos que no pueden avanzar y la CPU parada (`run` -> «stalled»).
STALLED = "GPU con warps vivos sin progreso (¿barrera?)"


def build_system(args) -> CpuGpuSystem:
    """El sistema de la línea de órdenes: periféricos y programa cargado.

    Lo usan los dos backends; el de Codon lo usa como espejo de su motor nativo
    (ventana, volcados e informe final, `tools/codon/host.py`).
    """
    system = CpuGpuSystem(
        args.memory_size, args.num_warps, args.warp_size,
        cpu_steps=args.cpu_steps, gpu_steps=args.gpu_steps,
        **sim_peripherals.from_arguments(args))
    system.load_cpu_program(load_program_file(args.program))
    return system


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    if args.backend == "codon":
        tracing = args.trace or args.trace_file is not None or args.trace_limit is not None
        if tracing or args.profile is not None or args.profile_annotate is not None:
            print("Codon: traza/profiling usan el motor Python de referencia", file=sys.stderr)
        else:
            from tools.codon_backend import run_cli
            try:
                return run_cli(list(sys.argv[1:] if argv is None else argv))
            except (OSError, ValueError, RuntimeError) as exc:
                print(f"Codon: {exc}", file=sys.stderr)
                return 2
    try:
        system = build_system(args)
        profile = sim_profile.from_arguments(args)
        if profile is not None:
            system.enable_profile(profile)
        sim_peripherals.start_display(system)
        tracing = (args.trace or args.trace_file is not None
                   or args.trace_limit is not None)
        output = (args.trace_file.open("w", encoding="utf-8") if args.trace_file
                  else nullcontext(sys.stderr))
        limited = stalled = None
        with output as stream:
            if tracing:
                system.enable_trace(stream, args.trace_limit)
            try:
                if system.run(args.run_limit,
                              max_cpu_instructions=args.cpu_run_limit,
                              max_gpu_instructions=args.gpu_run_limit) == "stalled":
                    stalled = STALLED
            except InstructionLimitExceeded as exc:
                limited = str(exc)
            except gpu_sim.SimulationError as exc:
                limited = str(exc)
            if tracing:
                print(f"FIN: {limited or stalled or 'HALT'}", file=stream, flush=True)
        sim_peripherals.write_outputs(args, system)
    except (OSError, ValueError) as exc:
        print(f"Simulador: {exc}", file=sys.stderr)
        return 2

    return finish_run(args, system, profile, limited, stalled)


def finish_run(args, system, profile=None, limited=None, stalled=None):
    cpu, gpu = system.cpu, system.gpu
    if cpu.error:
        print(f"CPU: ERROR 0x{cpu.error_code:02X} en PC=0x{cpu.error_pc:08X} "
              f"tras {cpu.instructions_executed} instrucciones")
    else:
        print(f"CPU: {'HALT' if cpu.halted else 'en marcha'} tras "
              f"{cpu.instructions_executed} instrucciones, PC=0x{cpu.pc:08X}")
    if gpu.fault:
        f = gpu.fault
        print(f"GPU: ERROR 0x{f.code:02X} en PC=0x{f.pc:08X}, warp={f.warp_id}, "
              f"hilo={f.core_id}, dirección={f.address}", file=sys.stderr)
    state = ("con error" if gpu.fault else "detenida" if gpu.halted_by_control
             else "ociosa" if not gpu.live else "con warps vivos")
    print(f"GPU: {state}, {gpu.retired} instrucciones de warp, "
          f"WARP_DONE=0x{gpu.done:X} WARP_LIVE=0x{gpu.live:X}")
    for i, value in enumerate(cpu.regs):
        if value != 0:
            print(f"R{i:02d} = 0x{value:08X} ({value})")
    if args.dump:
        address, size, filename = args.dump
        system.dump_memory(int(address, 0), int(size, 0), Path(filename))
    sim_profile.write_report(args, profile)
    sys.stdout.flush()
    sim_peripherals.finish_display(system)
    if limited or stalled:
        print(f"Simulador: {limited or stalled}", file=sys.stderr)
        return 2
    return 1 if cpu.error or gpu.fault else 0


if __name__ == "__main__":
    raise SystemExit(main())
