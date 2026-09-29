"""Retain seeded routing reports from a verified archived build.

Genérico: no depende de qué prototipo es. --report-dir es opcional: si se
omite, usa el último build archivado de --prototype con summary.json.

La pregunta que contesta
------------------------
*Cuántas semillas de las que se le den cumplen timing, en qué rango, y cuál
tiene más margen.* Siempre las corre todas.

Antes contestaba otra: se negaba a arrancar si el build de partida no cumplía,
y abortaba en la primera semilla que fallara. O sea que sólo servía para
confirmar un diseño ya sano — justo cuando no hace falta. El momento en que un
barrido vale algo es **después de una regresión**, cuando lo que hay que
averiguar es si el diseño se ha vuelto lento o es la semilla la que se cayó, y
ahí las dos guardas lo dejaban inservible. Pasó de verdad: la 19 se fue a
72,06 MHz tras la fase 3.5 y el barrido hubo que rehacerlo a mano.

Un `--seed` que falla timing **es un dato**, no un error: «cumplen tres de
ocho» dice algo muy distinto de «cumplen ocho de ocho», y ninguna de las dos
frases se puede escribir si el bucle se para en la primera que falla. El
`apio.ini` de cada carpeta está lleno de esas cuentas, y son el registro de si
un diseño tiene margen o vive de una semilla afortunada.

Lo que sí sigue siendo motivo para no empezar es que el build de partida no sea
de fiar —falló, es sólo archivo, o las fuentes cambiaron mientras se
construía—, porque entonces el netlist no representa a nada."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile
from build_report import (extract_log_details, nextpnr_flags, set_configured_seed,
                          summarize, timing_passes)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import (
    PrototypeResolutionError, find_repo_root, find_toolchain_binary,
    list_prototypes, oss_cad_suite_env, read_ecp5_params, resolve_prototype,
)


def latest_report_dir(prototype_dir: Path) -> Path:
    history = prototype_dir / 'reports'
    candidates = sorted(
        (d for d in history.iterdir() if (d / 'summary.json').exists()),
        reverse=True,
    ) if history.exists() else []
    if not candidates:
        raise SystemExit(f'No hay ningún build archivado en {history}. Ejecuta build primero, o indica --report-dir.')
    return candidates[0]


def load_results(path: Path) -> list:
    """results.json de un barrido anterior; vale la carpeta sweep-* o el fichero."""
    path = Path(path)
    if path.is_dir():
        path = path / 'results.json'
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f'No se puede leer el barrido de referencia {path}: {exc}')


def compare_sweeps(old: list, new: list, color: bool = None) -> list:
    """Líneas que comparan dos barridos con las MISMAS semillas.

    Con una sola semilla, la diferencia entre antes y después mezcla el efecto
    del cambio con el ruido del placement. Por eso se compara el conjunto: la
    mediana dice si el cambio mueve el diseño, el peor caso es lo que se
    declara, y el rango se enseña como referencia. Se llama ruido a un cambio de
    mediana menor que dos veces el error tipico de la diferencia entre los dos
    conjuntos (desviacion / raiz de n de cada uno); no es una prueba estadistica
    seria, pero con ocho semillas separa lo que el rango tapaba.
    """
    color = _use_color() if color is None else color
    seeds = sorted({r['seed'] for r in old} & {r['seed'] for r in new})
    if len(seeds) < 2:
        raise SystemExit('Hacen falta al menos 2 semillas en común para comparar barridos.')
    old = {r['seed']: r for r in old if r['seed'] in seeds}
    new = {r['seed']: r for r in new if r['seed'] in seeds}
    lines = [f'\nComparación con el barrido anterior ({len(seeds)} semillas comunes: '
             f'{" ".join(map(str, seeds))})']
    clocks = sorted(set.intersection(*(set(r['clocks']) for r in [*old.values(), *new.values()])))
    for clock in clocks:
        a = [old[s]['clocks'][clock]['achieved'] for s in seeds]
        b = [new[s]['clocks'][clock]['achieved'] for s in seeds]
        median_a, median_b = statistics.median(a), statistics.median(b)
        delta = median_b - median_a
        # Error tipico de la diferencia entre dos muestras independientes. El rango
        # de las semillas NO vale como ruido: con ocho semillas es tan ancho que
        # tapaba mejoras de +6 MHz con todas las semillas nuevas por encima de casi
        # todas las antiguas.
        noise = 2 * (statistics.variance(a) / len(a) + statistics.variance(b) / len(b)) ** 0.5
        if abs(delta) <= noise:
            verdict = _paint('dentro del ruido: no se distingue de cambiar de semilla', '33', color)
        else:
            verdict = (_paint('MEJORA', '32', color) if delta > 0
                       else _paint('EMPEORA', '31', color))
        lines.append(f'  {clock}: mediana {median_a:.2f} -> {median_b:.2f} ({delta:+.2f}), '
                     f'peor {min(a):.2f} -> {min(b):.2f} ({min(b) - min(a):+.2f}), '
                     f'rango {max(a) - min(a):.2f} -> {max(b) - min(b):.2f}: {verdict}')
    cumplen = [sum(r['passes'] for r in group.values()) for group in (old, new)]
    lines.append(f'  Cumplen: {cumplen[0]} de {len(seeds)} -> {cumplen[1]} de {len(seeds)}')
    return lines


def find_sweeps(prototype_dir: Path) -> list:
    """Carpetas sweep-* de todos los builds archivados, de más antigua a más nueva."""
    return sorted((prototype_dir / 'reports').glob('*/sweep-*'), key=lambda d: d.name)


def clock_stats(results: list) -> dict:
    return {clock: dict(
        worst=min(r['clocks'][clock]['achieved'] for r in results),
        median=statistics.median(r['clocks'][clock]['achieved'] for r in results),
        best=max(r['clocks'][clock]['achieved'] for r in results),
        required=results[0]['clocks'][clock]['constraint'])
        for clock in sorted(results[0]['clocks'])}


def _requested_seeds(folder: Path, results: list) -> list:
    try:
        return json.loads((folder / 'metadata.json').read_text())['seeds']
    except (OSError, json.JSONDecodeError, KeyError):
        return [r['seed'] for r in results]


def _options_text(folder: Path) -> str:
    """Las opciones extra de nextpnr con las que se hizo el barrido, o `-`."""
    try:
        options = json.loads((folder / 'metadata.json').read_text()).get('nextpnr_options') or []
    except (OSError, json.JSONDecodeError):
        options = []
    return ' '.join(options) or '-'


def _stamp(name: str) -> str:
    """20260929-132616 de 'sweep-20260929-132616-192231' o del nombre del build."""
    return name.removeprefix('sweep-')[:15]


def _use_color() -> bool:
    """Igual que build-list: solo en un terminal y si no hay NO_COLOR."""
    return sys.stdout.isatty() and 'NO_COLOR' not in os.environ


def _paint(text: str, code: str, color: bool = True) -> str:
    return f'\033[{code}m{text}\033[0m' if color else text


def _reaches(value: float, required: float) -> str:
    """Verde si el valor llega a lo exigido, rojo si no."""
    return '32' if value >= required else '31'


def _passing_code(passing: int, total: int) -> str:
    """Verde si cumplen todas las semillas, rojo si ninguna, amarillo si algunas."""
    return '32' if passing == total else '31' if passing == 0 else '33'


def _passing_cell(results: list) -> tuple:
    passing = sum(r['passes'] for r in results)
    return f'{passing}/{len(results)}', _passing_code(passing, len(results))


def _stat_cells(s: dict, margin: bool = False) -> tuple:
    """Peor / mediana / mejor coloreados contra lo exigido, y luego lo exigido."""
    cells = [(f'{s[key]:.2f}', _reaches(s[key], s['required'])) for key in ('worst', 'median', 'best')]
    cells.append(f'{s["required"]:.0f}')
    if margin:
        cells.append((f'{100 * (s["worst"] / s["required"] - 1):+.1f} %', _reaches(s['worst'], s['required'])))
    return tuple(cells)


def _table(rows: list, color: bool) -> list:
    """Alinea columnas. Una celda es un texto o (texto, color ANSI); None es una línea en blanco.

    Se rellena el texto plano y el color se pone después, para que los códigos
    ANSI no cuenten como ancho.
    """
    grid = [None if row is None else [c if isinstance(c, tuple) else (c, None) for c in row]
            for row in rows]
    widths = [max(len(row[i][0]) for row in grid if row) for i in range(len(rows[0]))]
    lines = []
    for row in grid:
        cells = [_paint(text, code, color and code is not None) + ' ' * (width - len(text))
                 for (text, code), width in zip(row, widths)] if row else []
        lines.append('  '.join(cells).rstrip())
    return lines


def list_sweeps(prototype_dir: Path, color: bool = None) -> list:
    """Una fila por barrido y reloj, para ver de un vistazo cómo ha ido el timing."""
    sweeps = find_sweeps(prototype_dir)
    if not sweeps:
        return [f'No hay barridos en {prototype_dir / "reports"}. Ejecuta build-sweep primero.']
    rows = [('BUILD', 'SWEEP', 'SEEDS', 'CUMPLEN', 'RELOJ', 'PEOR', 'MEDIANA', 'MEJOR', 'EXIGIDOS',
             'OPCIONES')]
    for folder in sweeps:
        try:
            results = json.loads((folder / 'results.json').read_text())
        except (OSError, json.JSONDecodeError):
            results = []
        head = (_stamp(folder.parent.name), _stamp(folder.name))
        opciones = _options_text(folder)
        if not results:
            rows.append((*head, '0', '-', '-', '-', '-', '-', 'sin resultados', opciones))
            continue
        requested = _requested_seeds(folder, results)
        seeds = str(len(results)) if len(results) == len(requested) else f'{len(results)}/{len(requested)}'
        cumplen = _passing_cell(results)
        for clock, s in clock_stats(results).items():
            rows.append((*head, seeds, cumplen, clock, *_stat_cells(s), opciones))
    return _table(rows, _use_color() if color is None else color)


def last_sweeps(root: Path, color: bool = None) -> list:
    """El barrido más reciente de cada prototipo que tenga alguno."""
    rows = [('PROTOTIPO', 'BUILD', 'SWEEP', 'SEEDS', 'CUMPLEN', 'RELOJ', 'PEOR', 'MEDIANA',
             'MEJOR', 'EXIGIDOS', 'MARGEN PEOR')]
    for prototype_dir in list_prototypes(root):
        sweeps = find_sweeps(prototype_dir)
        if not sweeps:
            continue
        folder = sweeps[-1]
        try:
            results = json.loads((folder / 'results.json').read_text())
        except (OSError, json.JSONDecodeError):
            results = []
        if len(rows) > 1:
            rows.append(None)  # línea en blanco entre prototipos: cada uno puede tener varios relojes
        head = (prototype_dir.name, _stamp(folder.parent.name), _stamp(folder.name))
        if not results:
            rows.append((*head, '0', '-', '-', '-', '-', '-', '-', 'sin resultados', ''))
            continue
        requested = _requested_seeds(folder, results)
        seeds = str(len(results)) if len(results) == len(requested) else f'{len(results)}/{len(requested)}'
        cumplen = _passing_cell(results)
        for n, (clock, s) in enumerate(clock_stats(results).items()):
            # Los datos del barrido solo en la primera fila: las demás son otros relojes.
            lead = (*head, seeds, cumplen) if n == 0 else ('',) * 5
            rows.append((*lead, clock, *_stat_cells(s, margin=True)))
    if len(rows) == 1:
        return ['Ningún prototipo tiene barridos todavía. Ejecuta build-sweep primero.']
    return _table(rows, _use_color() if color is None else color)


def resolve_sweep(prototype_dir: Path, spec: str) -> Path:
    """`latest`, una ruta, o un trozo del nombre del barrido (20260929-1405...)."""
    sweeps = find_sweeps(prototype_dir)
    if spec == 'latest':
        if not sweeps:
            raise SystemExit(f'No hay barridos en {prototype_dir / "reports"}.')
        return sweeps[-1]
    if Path(spec).is_dir():
        return Path(spec).resolve()
    matches = [d for d in sweeps if spec in d.name]
    if len(matches) != 1:
        raise SystemExit(f'"{spec}" coincide con {len(matches)} barridos; usa --list para ver '
                         f'los nombres o pasa la ruta completa.' if matches else
                         f'No hay ningún barrido que contenga "{spec}"; usa --list.')
    return matches[0]


def show_sweep(folder: Path, color: bool = None) -> list:
    """Detalle de un barrido: una fila por semilla, con el margen por reloj."""
    try:
        results = json.loads((folder / 'results.json').read_text())
    except (OSError, json.JSONDecodeError):
        results = []
    lines = [f'Barrido: {folder}', f'Build:   {folder.parent.name}']
    fallidas = sorted(
        d.name for d in folder.glob('seed-*')
        if not (d / 'summary.json').exists())
    if not results:
        return [*lines, 'Sin resultados.' + (f' Semillas sin informe: {", ".join(fallidas)}' if fallidas else '')]
    requested = _requested_seeds(folder, results)
    lines.append(f'Semillas pedidas: {" ".join(map(str, requested))}')
    lines.append(f'Opciones nextpnr: {_options_text(folder)}')
    color = _use_color() if color is None else color
    rows = [('SEMILLA', 'RESULTADO', 'RELOJES (MHz alcanzados/exigidos, margen)')]
    for r in sorted(results, key=lambda r: r['seed']):
        # La última columna lleva un color por reloj, así que se pinta a mano.
        clocks = ', '.join(
            _paint(f'{c} {v["achieved"]:.2f}/{v["constraint"]:.0f} '
                   f'({100 * (v["achieved"] / v["constraint"] - 1):+.1f} %)',
                   _reaches(v['achieved'], v['constraint']), color)
            for c, v in sorted(r['clocks'].items()))
        rows.append((str(r['seed']), ('OK', '32') if r['passes'] else ('NO', '31'), clocks))
    lines += _table(rows, color)
    if fallidas:
        lines.append(f'Sin informe (nextpnr falló o se interrumpió): {", ".join(fallidas)}')
    passing = sum(r['passes'] for r in results)
    lines.append(_paint(f'Cumplen {passing} de {len(results)}',
                        _passing_code(passing, len(results)), color))
    for clock, s in clock_stats(results).items():
        peor, mediana, mejor, exigidos = _stat_cells(s)
        lines.append(f'  {clock}: peor {_paint(*peor, color)}, mediana {_paint(*mediana, color)}, '
                     f'mejor {_paint(*mejor, color)}, exigidos {exigidos}')
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-p', '--prototype')
    parser.add_argument('--report-dir', type=Path, default=None)
    parser.add_argument('--seeds', type=int, nargs='+', default=[1, 2, 3, 4, 5])
    parser.add_argument('--apply', action='store_true',
                        help='escribe la semilla con más margen en el apio.ini del prototipo '
                             '(solo si alguna cumple timing)')
    parser.add_argument('--nextpnr-options', nargs='+', default=[], metavar='OPCION',
                        help='opciones extra de nextpnr, SIN guiones y con = para el valor: '
                             'tmg-ripup placer-heap-timingweight=30 router=router1. Para '
                             'medir si una opcion ayuda antes de ponerla en el apio.ini; '
                             'quedan anotadas en el barrido')
    parser.add_argument('--compare', type=Path, default=None, metavar='SWEEP',
                        help='carpeta sweep-* (o su results.json) de un barrido anterior con las '
                             'mismas semillas; compara mediana, peor caso y rango para saber si '
                             'un cambio de RTL mejora o empeora')
    parser.add_argument('--list', action='store_true',
                        help='lista los barridos ya hechos del prototipo (peor, mediana y mejor '
                             'por reloj)')
    parser.add_argument('--show', metavar='SWEEP', default=None,
                        help='detalle por semilla de un barrido: "latest", un trozo de su nombre '
                             '(ver --list) o su ruta')
    parser.add_argument('--last', action='store_true',
                        help='resumen del último barrido de cada prototipo que tenga alguno '
                             '(no necesita --prototype)')
    args = parser.parse_args()
    color = _use_color()
    if args.last:
        print('\n'.join(last_sweeps(find_repo_root(Path.cwd()))))
        return
    if args.prototype is None:
        parser.error('-p/--prototype es obligatorio (salvo con --last)')
    if args.list or args.show is not None:
        try:
            listed = resolve_prototype(args.prototype, root=find_repo_root(Path.cwd()))
        except PrototypeResolutionError as exc:
            raise SystemExit(f'error: {exc}')
        print(f'Using prototype: {listed.name}')
        print('\n'.join(list_sweeps(listed) if args.list
                        else show_sweep(resolve_sweep(listed, args.show))))
        return
    extra_flags = nextpnr_flags(args.nextpnr_options)
    reference = None
    if args.compare is not None:
        reference = load_results(args.compare)
        if {r['seed'] for r in reference} != set(args.seeds):
            raise SystemExit(f'--compare exige las mismas semillas que el barrido de referencia '
                             f'({sorted(r["seed"] for r in reference)}); has pasado {sorted(args.seeds)}.')
    repo_root = find_repo_root(Path.cwd())
    try:
        prototype_dir = resolve_prototype(args.prototype, root=repo_root)
    except PrototypeResolutionError as exc:
        raise SystemExit(f'error: {exc}')
    print(f'Using prototype: {prototype_dir.name}')
    source = (args.report_dir if args.report_dir is not None else latest_report_dir(prototype_dir)).resolve()
    metadata = json.loads((source / 'metadata.json').read_text())
    if metadata.get('exit_code') != 0 or metadata.get('archive_only') or metadata.get('sources_changed_during_build'):
        raise SystemExit('Require a successful, unchanged, non-archive-only build.')
    original = json.loads((source / 'hardware.pnr').read_text())
    # Que el netlist de partida no cumpla timing NO impide barrer: es el caso
    # en que el barrido hace falta. Se avisa, porque cambia cómo se lee el
    # resultado -- aquí el barrido no mide la dispersión de un diseño sano,
    # sino si hay alguna semilla que lo salve.
    if not timing_passes(original.get('fmax', {})):
        print('Aviso: el build de partida NO cumple timing; se barre igual.',
              flush=True)
    if len(set(args.seeds)) != len(args.seeds):
        raise SystemExit('Duplicate seeds are not independent samples.')
    folder = source / ('sweep-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir()
    exe = find_toolchain_binary('nextpnr-ecp5')
    env = oss_cad_suite_env()
    hashes = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
              for name in ('hardware.json', 'sources.zip')}
    (folder / 'metadata.json').write_text(json.dumps(dict(source=str(source), sha256=hashes,
        seeds=args.seeds, nextpnr_options=args.nextpnr_options,
        tool_sha256=hashlib.sha256(exe.read_bytes()).hexdigest()), indent=2))
    shutil.copy2(__file__, folder / 'sweep_report.py')
    params = read_ecp5_params((source / 'scons.params').read_text())
    results = []
    # Only the archived constraint is extracted, outside Apio's recursive tree.
    with tempfile.TemporaryDirectory(prefix='gpu-sweep-') as temporary:
        with zipfile.ZipFile(source / 'sources.zip') as archive:
            lpf_names = [name for name in archive.namelist() if name.endswith('.lpf')]
            if len(lpf_names) != 1:
                raise SystemExit(f'Se esperaba exactamente un .lpf en sources.zip; hay {lpf_names}')
            lpf = Path(temporary) / lpf_names[0]
            lpf.write_bytes(archive.read(lpf_names[0]))
        for seed in args.seeds:
            run = folder / f'seed-{seed}'
            run.mkdir()
            command = [str(exe), f"--{params['type']}", '--package', params['package'],
                '--speed', params['speed'],
                '--seed', str(seed), *extra_flags, '--json', str(source / 'hardware.json'),
                '--report', str(run / 'hardware.pnr'), '--lpf', str(lpf),
                '--textcfg', str(run / 'hardware.config'), '--timing-allow-fail',
                '--detailed-timing-report', '--force']
            (run / 'command.json').write_text(json.dumps(command, indent=2))
            print(f'Routing seed {seed}: {run}', flush=True)
            with (run / 'build.log').open('w', encoding='utf-8') as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env)
            extract_log_details(run)
            (run / 'exit_code.txt').write_text(str(result.returncode))
            # Que nextpnr reviente con una semilla es otra cosa que una semilla
            # que no cumple: no es un dato sobre el diseño. Se anota y se
            # sigue, para no perder las otras siete por una.
            if result.returncode:
                print(f'Seed {seed}: nextpnr falló; retenido en {run}', flush=True)
                continue
            summary = summarize(json.loads((run / 'hardware.pnr').read_text()))
            (run / 'summary.json').write_text(json.dumps(summary, indent=2))
            cumple = timing_passes(summary['clocks'])
            results.append(dict(seed=seed, clocks=summary['clocks'], passes=cumple))
            (folder / 'results.json').write_text(json.dumps(results, indent=2))
            print(f"{_paint('OK', '32', color) if cumple else _paint('NO', '31', color)} seed {seed}: "
                  + ', '.join(
                      f"{clock} {v['achieved']:.2f}/{v['constraint']:.0f} MHz"
                      for clock, v in sorted(summary['clocks'].items()))
                  , flush=True)
    if not results:
        raise SystemExit('Ninguna semilla llegó a producir un informe.')
    medians = {clock: statistics.median(r['clocks'][clock]['achieved'] for r in results)
               for clock in results[0]['clocks']}
    (folder / 'medians.json').write_text(json.dumps(medians, indent=2))

    # El resumen es lo que se pega en el apio.ini de la carpeta, así que dice
    # las tres cosas que ahí se apuntan: cuántas cumplen, en qué rango, y cuál
    # tiene más margen. Una mediana por debajo de la restricción significa que
    # el diseño está al borde y no que hubo mala suerte, y por eso se imprime
    # aunque alguna semilla cumpla.
    cumplen = [r for r in results if r['passes']]
    print('\n' + _paint(f'Cumplen {len(cumplen)} de {len(results)}',
                         _passing_code(len(cumplen), len(results)), color))
    for clock in sorted(results[0]['clocks']):
        valores = [r['clocks'][clock]['achieved'] for r in results]
        exigido = results[0]['clocks'][clock]['constraint']
        print(f'  {clock}: {_paint(f"{min(valores):.2f}", _reaches(min(valores), exigido), color)} a '
              f'{_paint(f"{max(valores):.2f}", _reaches(max(valores), exigido), color)} MHz, '
              f'mediana {_paint(f"{medians[clock]:.2f}", _reaches(medians[clock], exigido), color)}, '
              f'exigidos {exigido:.0f}')
    if cumplen:
        limitante = lambda r: min(  # noqa: E731 - el reloj con menos margen
            v['achieved'] / v['constraint'] for v in r['clocks'].values())
        mejor = max(cumplen, key=limitante)
        print(f'Más margen: semilla {mejor["seed"]} '
              f'({100 * (limitante(mejor) - 1):+.1f} % en su reloj más justo)')
        if args.apply:
            previous = set_configured_seed(prototype_dir, mejor['seed'], args.nextpnr_options)
            print(f'apio.ini: --seed {previous if previous is not None else "(ninguna)"}'
                  f' -> {mejor["seed"]}'
                  + (f', y opciones {" ".join(extra_flags)}' if extra_flags else '')
                  + '. El bitstream actual queda STALE hasta reconstruir.')
    else:
        print('Ninguna semilla cumple: aquí el problema ya no es la semilla.')
        if args.apply:
            print('--apply: no se toca el apio.ini.')
    if reference is not None:
        print('\n'.join(compare_sweeps(reference, results)))
    print(f'Informes: {folder}', flush=True)


if __name__ == '__main__':
    main()
