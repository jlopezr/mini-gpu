#!/usr/bin/env python3
"""Informe de las fixtures diferenciales de RTL: qué caso corre en qué prototipo.

    fixtures-report                 # matriz caso x prototipo + comprobaciones
    fixtures-report --prototype 22  # solo una columna

Imprime una matriz con el número `NN` que cada caso tiene en cada prototipo (el
de `fixtures/NN.*`) o `-` si ese prototipo lo omite, y debajo el motivo de cada
omisión. Después comprueba tres cosas y sale con 1 si alguna falla:

1. Un banco pide `examples/X.hex` y no hay `X.asm` en `x.tests`.
2. Un caso marcado `rtl.differential` que ningún prototipo usa.
3. Un programa que un banco pide por nombre y que ni un caso ni un README
   documentan: se ejecuta en la regresión pero nadie dice qué prueba.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import make_rtl_fixtures as gen  # noqa: E402
from tools import stage_programs  # noqa: E402
from tools.prototype import PrototypeResolutionError, find_repo_root, list_prototypes, resolve_prototype  # noqa: E402
from tools.rtl_facts import capabilities_from_rtl, load_capability_signals  # noqa: E402


def differential_prototypes(root: Path) -> list[Path]:
    return [p for p in list_prototypes(root) if gen.consumes_fixtures(p)]


def build_matrix(root: Path, prototypes: list[Path], candidates=None):
    """Una fila por caso: (caso, {numero de prototipo: (NN | None, [motivos])})."""
    candidates = gen.all_cases() if candidates is None else candidates
    signals = load_capability_signals(root)
    by_proto = {}
    for proto in prototypes:
        number = gen.prototype_number(proto)
        caps = capabilities_from_rtl(proto, signals)
        selected = gen.select_cases(candidates, caps, number)
        index = {c.name: i for i, c in enumerate(selected)}
        by_proto[number] = {c.name: (index.get(c.name), gen.omission_reasons(c, caps, number))
                            for c in candidates}
    return [(c, {n: by_proto[n][c.name] for n in by_proto}) for c in candidates]


def render_matrix(rows, numbers: list[str]) -> str:
    width = max([len('caso')] + [len(c.name) for c, _ in rows])
    lines = [f'{"caso":<{width}}  ' + '  '.join(f'{n:>3}' for n in numbers)]
    for case_, cells in rows:
        marks = [f'{cells[n][0]:02d}' if cells[n][0] is not None else ' -' for n in numbers]
        lines.append(f'{case_.name:<{width}}  ' + '  '.join(f'{m:>3}' for m in marks))
    omitted = [(c.name, n, cells[n][1]) for c, cells in rows for n in numbers if cells[n][0] is None]
    if omitted:
        lines += ['', 'Omisiones:']
        lines += [f'  {name} en {n}: {", ".join(reasons)}' for name, n, reasons in omitted]
    return '\n'.join(lines)


def bench_requests(prototype_dir: Path) -> dict[str, set[str]]:
    """banco -> programas `examples/<x>` que pide, sin extension."""
    found = {}
    for bench in sorted(prototype_dir.glob('*.v')):
        names = {name for name, _ in stage_programs.REFERENCIA.findall(
            bench.read_text(encoding='utf-8', errors='replace'))}
        if names:
            found[bench.name] = names
    return found


def _source_of(name: str):
    try:
        return stage_programs.buscar_fuente(name)
    except SystemExit as exc:  # dos fuentes con el mismo nombre
        return str(exc)


def documented(source: Path) -> bool:
    """Un caso que ejecuta ese programa, o un README de su carpeta que lo nombra."""
    test_json = source.parent / 'test.json'
    if test_json.exists():
        try:
            if json.loads(test_json.read_text(encoding='utf-8-sig')).get('program') == source.name:
                return True
        except ValueError:
            pass
    readme = source.parent / 'README.md'
    return readme.exists() and source.name in readme.read_text(encoding='utf-8', errors='replace')


def check(root: Path, rows, prototypes: list[Path]) -> list[str]:
    problems = []
    for case_, cells in rows:
        if all(idx is None for idx, _ in cells.values()):
            problems.append(f'caso diferencial que ningún prototipo usa: {case_.name}')
    for proto in prototypes:
        for bench, names in bench_requests(proto).items():
            for name in sorted(names):
                source = _source_of(name)
                where = f'{proto.name}/{bench}'
                if source is None:
                    problems.append(f'{where} pide examples/{name} y no hay {name}.asm en x.tests')
                elif isinstance(source, str):
                    problems.append(f'{where} pide examples/{name}: {source}')
                elif not documented(source):
                    problems.append(f'{where} usa {source.relative_to(root).as_posix()}, que ningún '
                                    f'caso ni README documenta')
    return sorted(set(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('-p', '--prototype', help='limita la matriz a un prototipo')
    args = parser.parse_args(argv)
    root = find_repo_root(Path.cwd())
    prototypes = differential_prototypes(root)
    if args.prototype:
        try:
            chosen = resolve_prototype(args.prototype, root=root)
        except PrototypeResolutionError as exc:
            print(f'error: {exc}', file=sys.stderr)
            return 2
        prototypes = [p for p in prototypes if p == chosen]
        if not prototypes:
            print(f'{chosen.name} no tiene banco diferencial (ningún banco incluye fixtures/count.vh)',
                  file=sys.stderr)
            return 2
    rows = build_matrix(root, prototypes)
    numbers = [gen.prototype_number(p) for p in prototypes]
    print(render_matrix(rows, numbers))

    # Los bancos por nombre se miran en todos los prototipos, no solo en los diferenciales.
    scope = prototypes if args.prototype else list_prototypes(root)
    problems = check(root, rows, scope)
    print()
    if problems:
        print(f'{len(problems)} problema(s):')
        print('\n'.join(f'  - {p}' for p in problems))
        return 1
    print('Sin problemas.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
