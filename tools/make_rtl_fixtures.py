#!/usr/bin/env python3
"""Generador compartido de fixtures diferenciales de RTL para los prototipos de GPU.

Sustituye a los `make_fixtures.py` que había copiados en cada prototipo. Toma los
casos de `x.tests/cases-gpu` marcados con `"rtl": {"differential": true}`, los
ensambla con `1.isa/mini_asm.py`, los ejecuta en el simulador funcional
(`11.gpu-sim-func`) y escribe en `<prototipo>/fixtures/` el estado que
`gpu_system_tb.v` compara contra el del RTL.

    python tools/make_rtl_fixtures.py --prototype 22

El formato de salida NO se puede tocar sin tocar el banco: los ficheros, su
orden y su contenido son lo que lee `$readmemh`.

La marca `rtl` de un `test.json`:

    "rtl": {
      "differential": true,
      "warp_config": "../../rtl-8-warps.json",   // opcional
      "exclude": ["12"]                           // opcional
    }

- `warp_config`: lanzamiento para el RTL, relativo al caso. Por defecto, el
  `warp_config` del propio caso. Existe porque el banco lanza 8 warps y hay
  casos cuyo `warps.json` lanza 1 o 2 (el simulador los prueba así), y el RTL
  perdería la cobertura multi-warp.
- `exclude`: números de prototipo que no lo ejecutan. Solo para lo que `requires`
  no sepa decir.

Cada caso se incluye en un prototipo solo si todo su `requires` está entre las
capacidades que `tools/rtl_facts.py` lee de su RTL. El orden es el de las rutas
de los casos, ordenadas, así que la numeración `NN` puede diferir entre
prototipos.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '1.isa'), str(ROOT / '11.gpu-sim-func')]

CASES_DIR = ROOT / 'x.tests' / 'cases-gpu'
SIM_MEMORY_BYTES = 128 * 1024
MAX_STEPS = 10000
WARP_SIZE = 8
RTL_KEYS = {'differential', 'warp_config', 'exclude'}


class Case(NamedTuple):
    name: str
    source: str
    config: dict | None = None
    requires: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


class RtlMarkError(ValueError):
    pass


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def rtl_mark(raw, where='caso'):
    """El bloque `rtl` de un test.json validado, o None si no es diferencial."""
    mark = raw.get('rtl')
    if mark is None:
        return None
    if not isinstance(mark, dict):
        raise RtlMarkError(f'{where}: rtl debe ser un objeto')
    unknown = set(mark) - RTL_KEYS
    if unknown:
        raise RtlMarkError(f'{where}: claves de rtl desconocidas: {", ".join(sorted(unknown))}')
    if not mark.get('differential'):
        return None
    exclude = mark.get('exclude', [])
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise RtlMarkError(f'{where}: rtl.exclude debe ser una lista de números de prototipo (cadenas)')
    return mark


def load_marked_cases(cases_dir=CASES_DIR):
    """Los casos marcados `rtl.differential`, por ruta ordenada."""
    cases_dir = Path(cases_dir)
    found = []
    for test_json in sorted(cases_dir.rglob('test.json'), key=lambda p: p.relative_to(cases_dir).as_posix()):
        where = test_json.parent.relative_to(cases_dir).as_posix()
        raw = _read_json(test_json)
        mark = rtl_mark(raw, where)
        if mark is None:
            continue
        if raw.get('architecture') != 'gpu':
            raise RtlMarkError(f'{where}: solo los casos de GPU pueden ser diferenciales de RTL')
        directory = test_json.parent
        config_name = mark.get('warp_config', raw.get('warp_config'))
        config = _read_json(directory / config_name) if config_name else None
        found.append(Case(
            name=where,
            source=(directory / raw['program']).read_text(encoding='utf-8'),
            config=config,
            requires=tuple(raw.get('requires', [])),
            exclude=tuple(mark.get('exclude', [])),
        ))
    return found


# --------------------------------------------------------------------------
# Programas que todavía viven aquí y no en x.tests.
#
# Son los 9 programas `regions_*` de test_simt_regions.py que tienen un caso
# parecido (no idéntico) en cases-gpu/simt. Se quedan hasta decidir si ese caso
# los sustituye en el diferencial: ver el informe de la fase 3.
# --------------------------------------------------------------------------
pending: list[Case] = []


def case(name, source, config=None, requires=()):
    pending.append(Case(name, source, config, tuple(requires)))


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


def all_cases(cases_dir=CASES_DIR):
    """Todos los casos candidatos, en el orden de las fixtures: primero los de
    x.tests por ruta y después los que aún viven aquí."""
    return load_marked_cases(cases_dir) + list(pending)


def consumes_fixtures(prototype_dir):
    """¿Algún banco del prototipo lee `fixtures/`? Se mira el `include` de count.vh
    en vez de fijar un nombre de banco: 29 lo llama `gpu_system_bl8_tb.v`."""
    for bench in sorted(Path(prototype_dir).glob('*_tb.v')):
        if 'fixtures/count.vh' in bench.read_text(encoding='utf-8', errors='replace'):
            return True
    return False


def prototype_number(prototype_dir):
    match = re.match(r'(\d+)', Path(prototype_dir).name)
    return match.group(1) if match else None


def omission_reasons(case_, capabilities, prototype=None):
    """Por qué un prototipo omite el caso; lista vacía si lo incluye."""
    reasons = [f'falta {name}' for name in sorted(set(case_.requires) - set(capabilities))]
    if prototype is not None and prototype in case_.exclude:
        reasons.append('excluido')
    return reasons


def select_cases(all_, capabilities, prototype=None):
    """Los casos aplicables a un prototipo, en el orden en que se declararon."""
    return [c for c in all_ if not omission_reasons(c, capabilities, prototype)]


def skipped_cases(all_, capabilities, prototype=None):
    """(caso, motivos) de lo que `select_cases` deja fuera."""
    return [(c, r) for c in all_ if (r := omission_reasons(c, capabilities, prototype))]


def write_fixtures(selected, out):
    """Escribe los fixtures de `selected` en `out`; devuelve cuántos casos son."""
    from mini_asm import assemble
    from minigpu_sim import System

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    metadata = []
    for index, (name, source, config, _requires, _exclude) in enumerate(selected):
        if config is not None and config.get('warp_size', WARP_SIZE) != WARP_SIZE:
            raise ValueError(f'{name}: el banco de RTL lanza warps de {WARP_SIZE} lanes')
        words = assemble(source)
        if len(words) > 256:
            raise ValueError(f'{name}: {len(words)} palabras; el banco carga 256')
        binary = struct.pack('<' + 'I' * len(words), *words)
        gpu = System(SIM_MEMORY_BYTES, 8, WARP_SIZE)
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
    number = prototype_number(prototype_dir)
    candidates = all_cases()
    selected = select_cases(candidates, capabilities, number)
    out = Path(args.out) if args.out else prototype_dir / 'fixtures'
    count = write_fixtures(selected, out)
    for case_, reasons in skipped_cases(candidates, capabilities, number):
        print(f'omitido {case_.name}: {", ".join(reasons)}')
    print(f'Generated {count} differential cases')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
