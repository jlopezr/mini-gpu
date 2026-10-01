#!/usr/bin/env python3
"""Generador compartido de fixtures diferenciales de RTL para los prototipos de GPU.

Sustituye a los `make_fixtures.py` que había copiados en cada prototipo. Ensambla
cada programa MiniISA con `1.isa/mini_asm.py`, lo ejecuta en el simulador
funcional (`11.gpu-sim-func`) y escribe en `<prototipo>/fixtures/` el estado que
`gpu_system_tb.v` compara contra el del RTL.

    python tools/make_rtl_fixtures.py --prototype 22

El formato de salida NO se puede tocar sin tocar el banco: los ficheros, su
orden y su contenido son lo que lee `$readmemh`. Cada caso declara en `requires`
las capacidades que el prototipo necesita para ejecutarlo (las mismas que usa
`x.tests`); un prototipo que no las tiene lo omite en vez de fallar en el RTL.
"""
from __future__ import annotations

import argparse
import json
import random
import struct
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '1.isa'), str(ROOT / '11.gpu-sim-func')]

SIM_MEMORY_BYTES = 128 * 1024
MAX_STEPS = 10000


class Case(NamedTuple):
    name: str
    source: str
    config: dict | None = None
    requires: tuple[str, ...] = ()


cases: list[Case] = []


def case(name, source, config=None, requires=()):
    cases.append(Case(name, source, config, tuple(requires)))


case('vector', '''
GETTID R1
MOVI R2, 4
MUL R3, R1, R2
ADDI R3, R3, 4096
ADDI R4, R1, 100
STORE R4, R3, 0
LOAD R5, R3, 0
BAR
HALT
''')
case('nested', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BLT R1, R2, low
MOVI R3, 30
BRA join
low:
MOVI R2, 2
SSY inner
BLT R1, R2, lowest
MOVI R3, 20
BRA inner
lowest:
MOVI R3, 10
inner:
ADDI R3, R3, 1
join:
ADDI R3, R3, 1
BAR
EXIT
''')
case('loop', '''
GETTID R1
ANDI R1, R1, 7
loop:
SSY done
BEQ R1, R0, done
ADDI R1, R1, -1
ADDI R3, R3, 1
BRA loop
done:
BAR
EXIT
''')
for name, first, second in [('exit_first','EXIT','MOVI R3, 7'),
                            ('exit_second','MOVI R3, 7','EXIT'),
                            ('exit_both','HALT','EXIT')]:
    case(name, f'''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BLT R1, R2, low
{first}
BRA join
low:
{second}
join:
ADDI R3, R3, 1
BAR
EXIT
''')
case('groups', 'BAR\nMOVI R3, 7\nBAR\nEXIT\nBAR\nMOVI R4, 9\nBAR\nEXIT',
     {'warps':[dict(id=w, pc=0 if w<4 else 16, active_mask=0x55 if w%2 else 0xff,
                    workgroup_id=w//4) for w in range(8)]})
case('finished_participant', 'BAR\nMOVI R3, 8\nEXIT',
     {'warps':[dict(id=0),dict(id=1,pc=8)]})
case('bank_conflicts', '''
GETTID R1
MOVI R2, 32
MUL R3, R1, R2
ADDI R3, R3, 4096
ADDI R4, R1, 123
STORE R4, R3, 0
LOAD R5, R3, 0
BAR
EXIT
''')
case('barrier_visibility', '''
GETTID R1
MOVI R2, 4
MUL R3, R1, R2
ADDI R3, R3, 4096
STORE R1, R3, 0
BAR
XORI R4, R1, 63
MUL R4, R4, R2
ADDI R4, R4, 4096
LOAD R5, R4, 0
BAR
HALT
''')
rng=random.Random(1288)
lines=['GETTID R1', 'MOVI R0, -17', 'MOVI R2, -3', 'MOVHI R3, 0x8000',
       'MOVI R4, 1', 'DIV R5, R3, R2', 'MOVI R2, -1', 'DIV R6, R3, R2',
       'MULFX R7, R0, R3', 'MOVHI R8, 0xffff', 'ORI R8, R8, 0x8001',
       'MULFX R9, R8, R8', 'NOP']
for op in ['ADD','SUB','MUL','MULFX','DIV','AND','OR','XOR','SHL','SHR','SAR']*3:
    # Divisor R4 is preserved and nonzero. R0 is hard-wired to zero: the MOVI R0 above
    # must be discarded and every R0 source operand must read 0.
    lines.append(f'{op} R{rng.randrange(10,32)}, R{rng.randrange(10)}, R{4 if op=="DIV" else rng.randrange(10)}')
lines += ['ANDI R10, R0, 0xff', 'XORI R11, R10, 0xffff', 'HALT']
case('arithmetic', '\n'.join(lines))
for op in ['BEQ','BNE','BLT','BGE','BLTU','BGEU']:
    case('branch_'+op.lower(), f'''
GETTID R1
ANDI R1, R1, 7
ADDI R1, R1, -4
SSY join
{op} R1, R0, taken
MOVI R3, 3
BRA join
taken:
MOVI R3, 7
join:
HALT
''')

case('unified_code', '''
LOAD R2, R0, 0
MOVHI R4, 0x40e0
ORI R4, R4, 123
STORE R4, R0, 64
BAR
BRA modified
NOP
NOP
NOP
NOP
NOP
NOP
NOP
NOP
NOP
NOP
modified:
HALT
HALT
''')
case('last_word', '''
MOVHI R1, 1
ORI R1, R1, 0xfffc
MOVI R2, 77
STORE R2, R1, 0
BAR
LOAD R3, R1, 0
HALT
''')
case('early_halt_unwind', '''
SSY outer
SSY inner
HALT
NOP
inner:
NOP
NOP
outer:
MOVI R3, 99
HALT
''')


# Reusable-region semantics, independently evaluated by the functional simulator.
case('regions_pending_loop', '''
GETTID R1
ANDI R1, R1, 7
loop:
SSY done
BEQ R1, R0, handler
ADDI R1, R1, -1
BRA loop
handler:
ADDI R3, R3, 10
BRA done
done:
ADDI R3, R3, 1
EXIT
''')

case('regions_nested_region_cannot_run_outer_pending_path_early', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY outer
BLT R1, R2, low
MOVI R2, 6
SSY inner
BLT R1, R2, middle
MOVI R3, 30
BRA inner
middle:
MOVI R3, 20
inner:
ADDI R3, R3, 1
BRA outer
low:
MOVI R3, 10
outer:
ADDI R3, R3, 1
BAR
EXIT
''')

case('regions_multiple_different_pending_destinations_in_one_region', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 2
SSY done
BLT R1, R2, low
MOVI R2, 5
BLT R1, R2, middle
MOVI R3, 30
BRA done
low:
MOVI R3, 10
BRA done
middle:
MOVI R3, 20
done:
ADDI R3, R3, 1
EXIT
''')

case('regions_fallthrough_join_parks_without_path', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BGE R1, R2, work
join:
ADDI R3, R3, 1
BAR
EXIT
work:
MOVI R3, 9
BRA join
''')

case('regions_direct_join_with_pending_path', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 2
SSY join
BLT R1, R2, low
MOVI R2, 5
BLT R1, R2, join
MOVI R3, 20
BRA join
low:
MOVI R3, 10
join:
ADDI R3, R3, 1
EXIT
''')

case('regions_identical_next_pcs_do_not_diverge_without_ssy', '''
GETTID R1
ANDI R1, R1, 7
BEQ R1, R0, next
next: ADDI R3, R3, 1
EXIT
''')

case('regions_sequential_regions_release_capacity_before_next_if', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY first
BLT R1, R2, first
ADDI R3, R3, 10
first:
SSY second
BGE R1, R2, second
ADDI R3, R3, 20
second:
ADDI R3, R3, 1
EXIT
''')

case('regions_exit_unwinds_inner_before_outer_pending_path', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY outer
BLT R1, R2, low
SSY inner
EXIT
inner:
MOVI R3, 99
BRA outer
low:
MOVI R3, 10
outer:
ADDI R3, R3, 1
EXIT
''')

case('regions_same_join_distinct_ssy_sites_open_distinct_regions', '''
SSY done
SSY done
SSY done
done: ADDI R3, R3, 1
EXIT
''')

case('regions_exit_inside_region_preserves_parked_lanes', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BLT R1, R2, join
EXIT
join:
ADDI R3, R3, 1
EXIT
''')

case('regions_last_exit_clears_both_stacks_and_keeps_next_pc', '''
SSY done
EXIT
done: MOVI R3, 99
''')

case('regions_long_escape_loop', '''
GETTID R1
ANDI R1, R1, 7
ADDI R1, R1, 20
loop: SSY done
BGE R2, R1, done
ADDI R2, R2, 1
BRA loop
done: ADDI R3, R2, 0
BAR
EXIT
''')


def consumes_fixtures(prototype_dir):
    """¿Algún banco del prototipo lee `fixtures/`? Se mira el `include` de count.vh
    en vez de fijar un nombre de banco: 29 lo llama `gpu_system_bl8_tb.v`."""
    for bench in sorted(Path(prototype_dir).glob('*_tb.v')):
        if 'fixtures/count.vh' in bench.read_text(encoding='utf-8', errors='replace'):
            return True
    return False


def select_cases(all_cases, capabilities):
    """Los casos aplicables a un prototipo, en el orden en que se declararon."""
    available = set(capabilities)
    return [c for c in all_cases if set(c.requires) <= available]


def skipped_cases(all_cases, capabilities):
    """(caso, capacidades que faltan) de lo que `select_cases` deja fuera."""
    available = set(capabilities)
    return [(c, sorted(set(c.requires) - available))
            for c in all_cases if not set(c.requires) <= available]


def write_fixtures(selected, out):
    """Escribe los fixtures de `selected` en `out`; devuelve cuántos casos son."""
    from mini_asm import assemble
    from minigpu_sim import System

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    metadata = []
    for index, (name, source, config, _requires) in enumerate(selected):
        words = assemble(source)
        binary = struct.pack('<' + 'I' * len(words), *words)
        gpu = System(SIM_MEMORY_BYTES, 8, 8)
        gpu.load_program(binary)
        if config is not None:
            gpu.configure_warps(config)
        initial = [(w.pc, w.active_mask, w.workgroup_id) for w in gpu.streaming_multiprocessor.warps]
        gpu.run(MAX_STEPS)
        assert not gpu.error, (name, gpu.fault)
        prefix = out / f'{index:02d}'
        prefix.with_suffix('.asm').write_text(source.strip() + '\n')
        prefix.with_suffix('.bin').write_bytes(binary)

        def hexfile(suffix, values):
            prefix.with_suffix(suffix).write_text(''.join(f'{v:08x}\n' for v in values))
        hexfile('.program.hex', words + [0] * (256 - len(words)))
        hexfile('.regs.hex', [r for w in gpu.streaming_multiprocessor.warps for lane in w.processors for r in lane.regs])
        hexfile('.memory.hex', struct.unpack('<512I', gpu.memory[4096:6144]))
        hexfile('.config.hex', [v for row in initial for v in row])
        hexfile('.counts.hex', [w.instructions_executed for w in gpu.streaming_multiprocessor.warps])
        hexfile('.state.hex', [v for w in gpu.streaming_multiprocessor.warps for v in (w.pc, w.active_mask, w.live_mask)])
        metadata.append(dict(id=index, name=name, instructions=gpu.instructions_executed))
    (out / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (out / 'count.vh').write_text(f'localparam CASES={len(selected)};\n')
    return len(selected)


def main(argv=None):
    from tools.prototype import PrototypeResolutionError, find_repo_root, resolve_prototype
    from tools.rtl_facts import capabilities_from_rtl, load_capability_signals

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('-p', '--prototype', required=True)
    parser.add_argument('--out', help='directorio de salida (por defecto <prototipo>/fixtures)')
    args = parser.parse_args(argv)
    root = find_repo_root(Path.cwd())
    try:
        prototype_dir = resolve_prototype(args.prototype, root=root)
    except PrototypeResolutionError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    capabilities = capabilities_from_rtl(prototype_dir, load_capability_signals(root))
    selected = select_cases(cases, capabilities)
    out = Path(args.out) if args.out else prototype_dir / 'fixtures'
    count = write_fixtures(selected, out)
    for case_, missing in skipped_cases(cases, capabilities):
        print(f'omitido {case_.name}: faltan {", ".join(missing)}')
    print(f'Generated {count} differential cases')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
