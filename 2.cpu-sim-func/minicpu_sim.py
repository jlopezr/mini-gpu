#!/usr/bin/env python3
"""Simulador funcional de MiniCPU para MiniISA v0.1.

Implementa todas las instrucciones actualmente definidas y el estado
arquitectónico de error:

- Sistema: NOP, GETTID y HALT.
- ALU: ADD, SUB, AND, OR, XOR, SHL, SHR y SAR, estas tres con cantidad en
  registro o inmediata (SHLI/SHRI/SARI, bit 10 del encoding).
- Aritmética: MUL, MULHI, MULFX, DIV, DIVU, REM y REMU.
- Inmediatas: MOVI, MOVHI, ADDI, ANDI, ORI y XORI.
- Memoria: LOAD y STORE, y los accesos de 8 y 16 bits LOADB, LOADUB,
  STOREB, LOADH, LOADUH y STOREH.
- Control: BEQ, BNE, BLT, BGE, BLTU, BGEU y BRA.
- Comparaciones materializadas: SLT y SLTU.
- Llamadas: JAL, JALR y JR.

El estado consta de PC y 32 registros de 32 bits. **R0 está cableado a cero**:
las escrituras se descartan y las lecturas valen siempre cero. Eso convierte
`JR Ra` en `JALR R0, Ra, 0` y deja `0x2E` reclamable; `JR` sigue implementado
por compatibilidad. Las operaciones hacen wrap módulo 2**32, los binarios son
little-endian y los branches son relativos a PC+4 con offsets expresados en
palabras de 32 bits.

Este modelo utiliza una memoria unificada y byte-addressed de 32 MiB por defecto,
que es la de los prototipos con SDRAM (10 y posteriores). El prototipo 6, en
BRAM, tiene 32 KiB contiguos (dos bancos de 16 KiB, programa y datos, con el bit
14 de la dirección eligiendo banco); ese es el único caso con un límite físico
más estrecho que el del simulador, y un programa destinado a él debe respetarlo
por su cuenta. Ver `docs/resumen-prototipos.md`, sección "Memoria".

Los errores detienen la CPU y conservan código y PC de la instrucción que los
provocó. No existen vectores de excepción ni reanudación.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Antes de los imports de abajo: `tools/` está en la raíz, `mini_asm` en `1.isa/`
# y el núcleo aquí, y el fichero se lanza también suelto.
HERE = Path(__file__).resolve().parent
for _folder in (HERE.parent / "1.isa", HERE.parent, HERE):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from mini_asm import load_program_bytes  # noqa: E402
from tools import sim_peripherals, sim_profile  # noqa: E402
# El modelo está en minicpu_core.py, que también compila el backend Codon. Lo que
# usa esta CLI, por su nombre; el resto se reexporta para quien importe este módulo.
from minicpu_core import CPU, InstructionLimitExceeded  # noqa: E402
from minicpu_core import *  # noqa: E402,F401,F403


def run_profiled(cpu, profile, max_instructions: int) -> None:
    """`CPU.run` pasando a `profile` (tools/sim_profile) cada instrucción retirada."""
    while not cpu.halted:
        cpu.check_limit(max_instructions)
        pc, before = cpu.pc, cpu.instructions_executed
        cpu.step()
        if cpu.instructions_executed != before:
            try:
                word = cpu.read_u32(pc)
            except RuntimeError:
                word = None
            profile.cpu(pc, word, cpu.pc)


def load_program_file(path: Path) -> bytes:
    """Acepta .asm, .bin o .hex. Misma funcion que usan minigpu_sim.py y
    minigpu_cycle.py: vive en 1.isa/mini_asm.py para que los tres carguen
    igual y `sim-cpu programa.asm` signifique lo mismo que `sim-gpu programa.asm`.
    """
    return load_program_bytes(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulador funcional de MiniCPU para MiniISA v0.1"
    )
    parser.add_argument("program", type=Path, help=".asm, .bin o .hex")
    parser.add_argument("--run-limit", type=int, default=100_000_000)
    parser.add_argument(
        "--memory-size",
        type=lambda value: int(value, 0),
        default=32 * 1024 * 1024,
        help="tamaño de memoria en bytes (admite 0x...)",
    )
    parser.add_argument(
        "--dump",
        nargs=3,
        metavar=("ADDRESS", "SIZE", "FILE"),
        help="vuelca una región de memoria después de ejecutar el programa",
    )
    sim_peripherals.add_arguments(parser)
    sim_profile.add_arguments(parser)
    args = parser.parse_args()

    try:
        sim_peripherals.warn_missing_video(args.program, args)
        cpu = CPU(args.memory_size, **sim_peripherals.from_arguments(args))
        program = load_program_file(args.program)
        profile = sim_profile.from_arguments(args)
    except (ValueError, OSError) as exc:
        # Una entrada mala no es un fallo del simulador, asi que no sale como
        # traceback. AsmError hereda de ValueError y cae aqui con linea y motivo.
        print(f"Simulador: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    cpu.load_program(program)
    sim_peripherals.start_display(cpu)
    limited = None
    try:
        if profile is None:
            cpu.run(args.run_limit)
        else:
            run_profiled(cpu, profile, args.run_limit)
    except InstructionLimitExceeded as exc:
        # No es un fallo del simulador: el programa no paró dentro del límite.
        # Un programa interactivo con bucle principal acaba así, y las salidas
        # (framebuffer, consola, serie) siguen siendo lo que se quería ver.
        limited = str(exc)
    sim_peripherals.write_outputs(args, cpu)

    if limited:
        print(f"Simulador: {limited} tras {cpu.instructions_executed} instrucciones "
              f"(--run-limit {args.run_limit})", file=sys.stderr)
    elif cpu.error:
        print(
            f"ERROR 0x{cpu.error_code:02X} en PC=0x{cpu.error_pc:08X} "
            f"tras {cpu.instructions_executed} instrucciones"
        )
    else:
        print(f"HALT tras {cpu.instructions_executed} instrucciones")
    print(f"PC = 0x{cpu.pc:08X}")
    for i, value in enumerate(cpu.regs):
        if value != 0:
            print(f"R{i:02d} = 0x{value:08X} ({value})")

    if args.dump is not None:
        address_text, size_text, filename_text = args.dump
        address = int(address_text, 0)
        size = int(size_text, 0)
        filename = Path(filename_text)

        cpu.dump_memory(address, size, filename)
        print(
            f"Volcados {size} bytes desde 0x{address:08X} "
            f"a {filename}"
        )

    sim_profile.write_report(args, profile)
    sys.stdout.flush()
    sim_peripherals.finish_display(cpu)
    if limited:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
