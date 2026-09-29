"""El "muro" de caminos casi criticos de un build de nextpnr, por modulo y registro.

Un build que cierra timing con poca holgura no suele tener UN camino malo: tiene
cientos casi igual de malos, y arreglar el peor solo descubre el siguiente.
Esto lo enseña de un vistazo -- que registros de destino llegan tarde, de que
modulos son y cuantos son-- y permite comparar dos builds para ver si un cambio
mueve el muro o solo el primer camino.

Lee el informe que nextpnr escribe con `--detailed-timing-report`
(`detailed_net_timings` dentro de `hardware.pnr`): un build normal no lo trae,
pero TODA semilla de `build-sweep` si. Sin detalle, con `--prototype` se usa el
ultimo barrido.

`LLEGADA` es el tiempo acumulado hasta el destino, contado desde el flanco de
reloj, como el ultimo numero de un camino critico. El periodo es el del reloj
elegido (el de menos margen si no se dice), asi que `HOLGURA = periodo - llegada`.
El resto de dominios y las rutas de entrada y salida de pin no se miran.
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import PrototypeResolutionError, find_repo_root, resolve_prototype  # noqa: E402

# Fracciones del periodo a partir de las cuales un destino cuenta como casi
# critico. A 80 MHz son 10,0 y 11,25 ns.
NEAR = 0.80
HARD = 0.90


def load_pnr(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f'No se puede leer {path}: {exc}')


def has_detail(pnr):
    return bool(pnr.get('detailed_net_timings'))


def best_seed_folder(sweep_folder):
    """La semilla de un barrido con mas margen en su reloj mas justo."""
    sweep_folder = Path(sweep_folder)
    try:
        results = json.loads((sweep_folder / 'results.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        results = []
    if not results:
        raise SystemExit(f'{sweep_folder} no tiene results.json con semillas.')
    margin = lambda r: min(v['achieved'] / v['constraint'] for v in r['clocks'].values())  # noqa: E731
    return sweep_folder / f'seed-{max(results, key=margin)["seed"]}'


def pnr_from_path(path):
    """Un .pnr, una carpeta seed-N, o un barrido (se toma su mejor semilla)."""
    path = Path(path)
    if path.is_file():
        return path
    if (path / 'hardware.pnr').is_file():
        return path / 'hardware.pnr'
    if (path / 'results.json').is_file():
        return best_seed_folder(path) / 'hardware.pnr'
    raise SystemExit(f'{path} no es un hardware.pnr, una carpeta seed-N ni un barrido.')


def sweeps_of(prototype_dir):
    return sorted((Path(prototype_dir) / 'reports').glob('*/sweep-*'), key=lambda d: d.name)


def resolve_source(prototype_dir, sweep=None, seed=None):
    """(ruta al .pnr, nota) para un prototipo: el ultimo build, o un barrido."""
    prototype_dir = Path(prototype_dir)
    if sweep is not None:
        candidates = sweeps_of(prototype_dir)
        if sweep == 'latest':
            matches = candidates[-1:]
        elif Path(sweep).is_dir():
            matches = [Path(sweep)]
        else:
            matches = [d for d in candidates if sweep in d.name]
        if len(matches) != 1:
            raise SystemExit(f'"{sweep}" coincide con {len(matches)} barridos; '
                             f'usa build-sweep --list para ver los nombres.')
        folder = matches[0] / f'seed-{seed}' if seed is not None else best_seed_folder(matches[0])
        return folder / 'hardware.pnr', f'barrido {matches[0].name}, {folder.name}'
    builds = sorted(d for d in (prototype_dir / 'reports').glob('*') if (d / 'hardware.pnr').is_file())
    if builds:
        return builds[-1] / 'hardware.pnr', f'build {builds[-1].name}'
    raise SystemExit(f'{prototype_dir.name} no tiene builds archivados.')


def pick_clock(pnr, wanted=None):
    """(nombre, exigido MHz, alcanzado MHz) del reloj pedido o del de menos margen."""
    fmax = pnr.get('fmax', {})
    if not fmax:
        raise SystemExit('El informe no trae fmax: no se sabe que reloj mirar.')
    if wanted:
        matches = [c for c in fmax if wanted in c]
        if len(matches) != 1:
            raise SystemExit(f'"{wanted}" coincide con {len(matches)} relojes: {", ".join(fmax)}')
        name = matches[0]
    else:
        name = min(fmax, key=lambda c: fmax[c]['achieved'] / fmax[c]['constraint'])
    return name, fmax[name]['constraint'], fmax[name]['achieved']


def family(cell):
    """`dmem_adapter_i.wb_data_TRELLIS_FF_Q_107` -> `dmem_adapter_i.wb_data`."""
    cell = re.sub(r'_TRELLIS_FF_Q.*|_TRELLIS_RAMW.*|\.\d+.*$', '', cell)
    cell = re.sub(r'\[\d+\]', '', cell)
    return re.sub(r'_\d+$', '', cell)


def module(cell):
    match = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\.', cell)
    return match.group(1) if match else '(anonimo)'


def analyze(pnr, clock=None):
    """Familias de registros de destino de un reloj, con su peor llegada y cuantos pasan de 80 % y 90 %."""
    if not has_detail(pnr):
        raise SystemExit('Este informe no trae detalle por red (`detailed_net_timings`): '
                         'hace falta un barrido, o `--detailed-timing-report` en el apio.ini.')
    name, constraint, achieved = pick_clock(pnr, clock)
    period = 1000.0 / constraint
    families = {}
    endpoints = 0
    for net in pnr['detailed_net_timings']:
        if name not in net.get('event', ''):
            continue
        for ep in net.get('endpoints', []):
            cell = ep.get('cell', '')
            if '$tr_io' in cell:      # pines: el rutado hasta ellos no se cronometra aqui
                continue
            delay = ep['delay']
            arrival = max(delay) if isinstance(delay, list) else delay
            entry = families.setdefault(family(cell), dict(module=module(cell), worst=0.0,
                                                           near=0, hard=0, endpoints=0))
            entry['worst'] = max(entry['worst'], arrival)
            entry['near'] += arrival >= NEAR * period
            entry['hard'] += arrival >= HARD * period
            entry['endpoints'] += 1
            endpoints += 1
    return dict(clock=name, constraint=constraint, achieved=achieved, period=period,
                endpoints=endpoints, families=families,
                near=sum(f['near'] for f in families.values()),
                hard=sum(f['hard'] for f in families.values()))


def by_module(analysis):
    modules = collections.defaultdict(lambda: dict(worst=0.0, near=0, hard=0))
    for entry in analysis['families'].values():
        m = modules[entry['module']]
        m['worst'] = max(m['worst'], entry['worst'])
        m['near'] += entry['near']
        m['hard'] += entry['hard']
    return modules


# ---- presentacion ---------------------------------------------------------

def _use_color():
    return sys.stdout.isatty() and 'NO_COLOR' not in os.environ


def _paint(text, code, color):
    return f'\033[{code}m{text}\033[0m' if color and code else text


def _table(rows, color):
    """Filas de celdas (texto o (texto, codigo ANSI)); se rellena el texto plano y luego se pinta."""
    grid = [[c if isinstance(c, tuple) else (c, None) for c in row] for row in rows]
    widths = [max(len(r[i][0]) for r in grid) for i in range(len(grid[0]))]
    return [('  '.join(_paint(t, c, color) + ' ' * (w - len(t))
                        for (t, c), w in zip(row, widths))).rstrip() for row in grid]


def _arrival_cell(value, period):
    code = '31' if value >= period else '33' if value >= HARD * period else None
    return f'{value:.2f}', code


def _header(analysis, source=None):
    p = analysis['period']
    lines = []
    if source:
        lines.append(f'Fuente: {source}')
    lines.append(f'Reloj: {analysis["clock"]}   exigido {analysis["constraint"]:.1f} MHz '
                 f'(periodo {p:.2f} ns)   alcanzado {analysis["achieved"]:.2f} MHz '
                 f'({1000 / analysis["achieved"]:.2f} ns)')
    lines.append(f'Destinos con llegada >= {int(NEAR * 100)} % del periodo ({NEAR * p:.2f} ns): '
                 f'{analysis["near"]} de {analysis["endpoints"]}; '
                 f'>= {int(HARD * 100)} % ({HARD * p:.2f} ns): {analysis["hard"]}')
    return lines


def report_lines(analysis, top=20, source=None, color=False):
    p = analysis['period']
    lines = _header(analysis, source) + ['']
    ranked = sorted(analysis['families'].items(), key=lambda kv: -kv[1]['worst'])[:top]
    rows = [('REGISTRO DE DESTINO', 'MODULO', 'LLEGADA', 'HOLGURA', '>=80 %', '>=90 %')]
    for name, e in ranked:
        rows.append((name, e['module'], _arrival_cell(e['worst'], p), f'{p - e["worst"]:+.2f}',
                     str(e['near']), str(e['hard'])))
    lines += _table(rows, color) + ['']
    rows = [('MODULO', 'LLEGADA', '>=80 %', '>=90 %')]
    modules = sorted(by_module(analysis).items(), key=lambda kv: -kv[1]['worst'])
    for name, m in modules[:12]:
        rows.append((name, _arrival_cell(m['worst'], p), str(m['near']), str(m['hard'])))
    return lines + _table(rows, color)


def compare_lines(a, b, top=20, source_a=None, source_b=None, color=False):
    """Familias de dos builds lado a lado: baja la llegada, o baja el numero de destinos?"""
    p = a['period']
    lines = [f'A: {source_a or "(primero)"}', f'B: {source_b or "(segundo)"}',
             f'Reloj {a["clock"]}: A {a["achieved"]:.2f} MHz -> B {b["achieved"]:.2f} MHz',
             f'Destinos >= {int(NEAR * 100)} % del periodo: {a["near"]} -> {b["near"]};  '
             f'>= {int(HARD * 100)} %: {a["hard"]} -> {b["hard"]}', '']
    names = set(a['families']) | set(b['families'])
    empty = dict(module='', worst=0.0, near=0, hard=0)
    score = lambda n: max(a['families'].get(n, empty)['worst'], b['families'].get(n, empty)['worst'])  # noqa: E731
    rows = [('REGISTRO DE DESTINO', 'LLEGADA A', 'LLEGADA B', 'DELTA', '>=80 % A', '>=80 % B')]
    for name in sorted(names, key=score, reverse=True)[:top]:
        fa, fb = a['families'].get(name, empty), b['families'].get(name, empty)
        delta = fb['worst'] - fa['worst']
        code = '32' if delta <= -0.2 else '31' if delta >= 0.2 else None
        rows.append((name, _arrival_cell(fa['worst'], p) if fa['worst'] else '-',
                     _arrival_cell(fb['worst'], p) if fb['worst'] else '-',
                     (f'{delta:+.2f}' if fa['worst'] and fb['worst'] else '-', code),
                     str(fa['near']), str(fb['near'])))
    return lines + _table(rows, color)


# ---- linea de comandos ----------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     epilog='Ejemplos:  timing-wall -p 30   |   timing-wall -p 30 --sweep latest '
                                            '--seed 5   |   timing-wall A/hardware.pnr --compare B/hardware.pnr')
    parser.add_argument('source', nargs='?', type=Path,
                        help='un hardware.pnr, una carpeta seed-N o un barrido (se toma su mejor semilla)')
    parser.add_argument('-p', '--prototype', help='usa el ultimo build de este prototipo')
    parser.add_argument('--sweep', help='con --prototype: un barrido ("latest", un trozo de su nombre o su ruta)')
    parser.add_argument('--seed', type=int, help='con --sweep: la semilla (por defecto la de mas margen)')
    parser.add_argument('--compare', type=Path, metavar='OTRO',
                        help='segundo informe (mismos tipos de ruta que SOURCE) para comparar lado a lado')
    parser.add_argument('--clock', help='trozo del nombre del reloj (por defecto, el de menos margen)')
    parser.add_argument('--top', type=int, default=20, help='cuantas familias enseñar (20)')
    args = parser.parse_args(argv)

    if args.source is not None:
        path, note = pnr_from_path(args.source), str(args.source)
    elif args.prototype:
        try:
            prototype_dir = resolve_prototype(args.prototype, root=find_repo_root(Path.cwd()))
        except PrototypeResolutionError as exc:
            raise SystemExit(f'error: {exc}')
        path, note = resolve_source(prototype_dir, args.sweep, args.seed)
        pnr = load_pnr(path)
        if not has_detail(pnr) and args.sweep is None:
            sweeps = sweeps_of(prototype_dir)
            if not sweeps:
                raise SystemExit(f'El ultimo build de {prototype_dir.name} no trae detalle por red y no '
                                 f'hay barridos: ejecuta build-sweep o pon --detailed-timing-report.')
            path, note = resolve_source(prototype_dir, sweeps[-1].name, None)
            note += ' (el build no trae detalle por red; se usa el ultimo barrido)'
    else:
        parser.error('indica un informe o --prototype')
    analysis = analyze(load_pnr(path), args.clock)
    color = _use_color()
    if args.compare is not None:
        other = pnr_from_path(args.compare)
        second = analyze(load_pnr(other), analysis['clock'])
        print('\n'.join(compare_lines(analysis, second, args.top, f'{note} ({path})', str(other), color)))
    else:
        print('\n'.join(report_lines(analysis, args.top, f'{note} ({path})', color)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
