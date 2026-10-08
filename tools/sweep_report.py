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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from build_report import (_metadata_source_hashes, configured_options, configured_seed,
                          default_env, extract_log_details, nextpnr_flags,
                          set_configured_seed, summarize, synthesizable_source_hashes,
                          timing_passes)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import (
    PrototypeResolutionError, find_oss_cad_suite, find_repo_root, find_toolchain_binary,
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


def margin(result: dict) -> float:
    """Holgura de una semilla: la del reloj con menos margen (1.0 = justo)."""
    return min(v['achieved'] / v['constraint'] for v in result['clocks'].values())


def best_seed(results: list) -> dict:
    """La semilla que cumple con mas margen en su reloj mas justo, o None."""
    passing = [r for r in results if r['passes']]
    return max(passing, key=margin) if passing else None


def best_per_clock(results: list) -> dict:
    """Por reloj, la semilla que cumple (todos los relojes) con mas holgura en ese."""
    passing = [r for r in results if r['passes']]
    return {clock: max(passing, key=lambda r: r['clocks'][clock]['achieved']
                       / r['clocks'][clock]['constraint'])
            for clock in (passing[0]['clocks'] if passing else {})}


def best_per_clock_lines(results: list, chosen: int = None, color: bool = None) -> list:
    """Tabla 'mejor semilla por reloj' para decidir a mano cuando discrepan.

    Solo semillas que cumplen todos los relojes. `chosen` marca la que
    `--promote` sin valor adoptaria."""
    best = best_per_clock(results)
    if len({r['seed'] for r in best.values()}) < 2:
        return []        # una sola semilla es la mejor en todo: no hay nada que decidir
    color = _use_color() if color is None else color
    width = max(len(c) for c in best)
    lines = ['Mejor semilla por reloj (solo las que cumplen todos):']
    for clock, r in sorted(best.items()):
        v = r['clocks'][clock]
        tag = '  <- la de mas margen global' if r['seed'] == chosen else ''
        lines.append(f'  {clock:<{width}}  semilla {r["seed"]:>3}  '
                     + _paint(f'{v["achieved"]:.2f}/{v["constraint"]:.0f} MHz '
                              f'({100 * (v["achieved"] / v["constraint"] - 1):+.1f} %)',
                              _reaches(v['achieved'], v['constraint']), color) + tag)
    return lines


def promote_seed(prototype_dir: Path, sweep: Path, seed: int) -> Path:
    """Convierte una semilla de un barrido en un build archivado y en el bitstream.

    El barrido guarda `hardware.config` y `hardware.pnr` por semilla, pero no el
    `.bit` ni deja nada en `_build/`, y cambiar el `apio.ini` invalida el hash del
    build anterior. Con la misma semilla y el mismo netlist nextpnr es
    determinista, asi que en vez de volver a sintetizar se empaqueta el `.config`
    con `ecppack` (segundos) y se archiva como un build mas.

    Adoptar la semilla incluye escribirla en el `apio.ini`, junto con las
    opciones de nextpnr con las que se barrio: una semilla solo vale con ellas.
    Se niega si las fuentes ya no son las del build que se barrio, o si la
    semilla no cumple timing; el `apio.ini` no se toca en esos casos.
    """
    run = sweep / f'seed-{seed}'
    for name in ('hardware.config', 'hardware.pnr', 'summary.json'):
        if not (run / name).is_file():
            raise SystemExit(f'La semilla {seed} no tiene {name} en {sweep.name}.')
    if (run / 'exit_code.txt').read_text().strip() != '0':
        raise SystemExit(f'nextpnr fallo con la semilla {seed}; no hay nada que promover.')
    summary = json.loads((run / 'summary.json').read_text())
    if not timing_passes(summary['clocks']):
        raise SystemExit(f'La semilla {seed} no cumple timing; no se promueve.')
    sweep_meta = json.loads((sweep / 'metadata.json').read_text())
    source = sweep.parent
    source_meta = json.loads((source / 'metadata.json').read_text())
    if source_meta.get('exit_code') != 0 or source_meta.get('sources_changed_during_build'):
        raise SystemExit('El build de partida del barrido no es de fiar.')

    current = synthesizable_source_hashes(prototype_dir)
    rtl = lambda hashes: {k: v for k, v in hashes.items() if k != 'apio.ini'}  # noqa: E731
    if rtl(_metadata_source_hashes(source_meta)) != rtl(current):
        raise SystemExit('Las fuentes han cambiado desde el build que se barrio; '
                         'reconstruye y vuelve a barrer.')
    suite = find_oss_cad_suite()
    ecppack = find_toolchain_binary('ecppack')
    # Fijar la semilla y las opciones con las que se midio es parte de adoptarla:
    # el archivo lleva el hash del apio.ini nuevo. Si algo falla despues, el
    # apio.ini vuelve a como estaba.
    ini = prototype_dir / 'apio.ini'
    original_ini = ini.read_bytes()
    swept_options = sweep_meta.get('nextpnr_options', [])
    previous = set_configured_seed(prototype_dir, seed, swept_options)
    print(f'apio.ini: --seed {previous if previous is not None else "(ninguna)"} -> {seed}'
          + (f', y opciones {" ".join(nextpnr_flags(swept_options))}' if swept_options else ''))
    try:
        return _archive_promotion(prototype_dir, sweep, run, seed, summary, suite, ecppack,
                                  source)
    except BaseException:
        ini.write_bytes(original_ini)
        raise


def _archive_promotion(prototype_dir, sweep, run, seed, summary, suite, ecppack, source):
    """Segunda mitad de `promote_seed`: empaqueta, archiva y deja `_build/`."""
    folder = prototype_dir / 'reports' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                                          + f'-promote-seed{seed}')
    folder.mkdir()
    hashes = {}
    with zipfile.ZipFile(folder / 'sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for pattern in ('*.v', '*.sv', '*.vh', '*.ini', '*.lpf', '*.ps1', '*.py', 'sim/*.vh',
                        'fonts/*.hex'):
            for src in prototype_dir.glob(pattern):
                relative = src.relative_to(prototype_dir)
                data = src.read_bytes()
                archive.writestr(str(relative), data)
                hashes[str(relative)] = hashlib.sha256(data).hexdigest()
    command = [str(ecppack), '--compress', '--db', str(suite / 'share' / 'trellis' / 'database'),
               str(run / 'hardware.config'), str(folder / 'hardware.bit')]
    started = datetime.now()
    result = subprocess.run(command, capture_output=True, text=True, env=oss_cad_suite_env())
    if result.returncode:
        shutil.rmtree(folder)
        raise SystemExit(f'ecppack fallo:\n{result.stdout}{result.stderr}')
    for name in ('hardware.config', 'hardware.pnr', 'summary.json', 'build.log'):
        shutil.copy2(run / name, folder / name)
    for name in ('hardware.json', 'scons.params'):
        shutil.copy2(source / name, folder / name)
    (folder / 'metadata.json').write_text(json.dumps(dict(
        label=f'promote-seed{seed}', archive_only=False, incremental=False,
        command=command, source_sha256=hashes, started=started.isoformat(),
        exit_code=0, elapsed_seconds=(datetime.now() - started).total_seconds(),
        sources_changed_during_build=[], promoted_from=str(run),
        sweep_sha256={n: hashlib.sha256((run / n).read_bytes()).hexdigest()
                      for n in ('hardware.config', 'hardware.pnr')}), indent=2),
        encoding='utf-8')
    (folder / 'summary.txt').write_text(
        f'Label: promote-seed{seed}\nPromoted from {run}\n' + ''.join(
            f'{c}: {v["achieved"]:.2f} MHz; required {v["constraint"]:.2f} MHz\n'
            for c, v in summary['clocks'].items()), encoding='utf-8')
    build_dir = prototype_dir / '_build' / default_env(prototype_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    for name in ('hardware.bit', 'hardware.config', 'hardware.pnr', 'hardware.json'):
        shutil.copy2(folder / name, build_dir / name)
    return folder


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
    parser.add_argument('--seeds', type=int, nargs='+', default=None,
                        help='semillas a barrer (por defecto 1 2 3 4 5)')
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 3) // 3),
                        help='semillas en paralelo (por defecto un tercio de los hilos: nextpnr '
                             'es monohilo y usa unos 500 MB). No cambia ningun resultado')
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
    parser.add_argument('--promote', nargs='?', const='best', default=None, metavar='SEMILLA',
                        help='adopta una semilla: la escribe en el apio.ini con las opciones con '
                             'que se barrio y la convierte en build archivado y en '
                             '_build/hardware.bit, sin volver a sintetizar. Sin valor, la que '
                             'cumple con mas margen; con valor, esa (si cumple). Con --seeds '
                             'actua al terminar el barrido; sin --seeds, sobre un barrido ya '
                             'hecho (el ultimo, o el de --from). Si ninguna cumple, no toca nada')
    parser.add_argument('--from', dest='from_sweep', default='latest', metavar='SWEEP',
                        help='barrido del que promover: "latest", un trozo de su nombre o su ruta')
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
    if args.promote is not None and args.promote != 'best':
        try:
            args.promote = int(args.promote)
        except ValueError:
            parser.error('--promote admite una semilla (entero) o nada, para la de mas margen')
    if args.promote is not None and args.seeds is None:
        try:
            target = resolve_prototype(args.prototype, root=find_repo_root(Path.cwd()))
        except PrototypeResolutionError as exc:
            raise SystemExit(f'error: {exc}')
        print(f'Using prototype: {target.name}')
        existing = resolve_sweep(target, args.from_sweep)
        seed = args.promote
        if seed == 'best':
            chosen = best_seed(load_results(existing))
            if chosen is None:
                raise SystemExit(f'Ninguna semilla de {existing.name} cumple timing: no se '
                                 f'adopta ninguna y el apio.ini queda como esta.')
            seed = chosen['seed']
        folder = promote_seed(target, existing, seed)
        print(f'Adoptada la semilla {seed}: {folder}')
        return
    if args.from_sweep != 'latest':
        parser.error('--from solo tiene sentido con --promote y sin --seeds')
    if args.list or args.show is not None:
        try:
            listed = resolve_prototype(args.prototype, root=find_repo_root(Path.cwd()))
        except PrototypeResolutionError as exc:
            raise SystemExit(f'error: {exc}')
        print(f'Using prototype: {listed.name}')
        print('\n'.join(list_sweeps(listed) if args.list
                        else show_sweep(resolve_sweep(listed, args.show))))
        return
    if args.seeds is None:
        args.seeds = [1, 2, 3, 4, 5]
    if isinstance(args.promote, int) and args.promote not in args.seeds:
        parser.error(f'--promote {args.promote}: esa semilla no esta entre las que se barren')
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
        def route(seed):
            """Una semilla entera. Cada una vive en su carpeta, asi que en paralelo
            no comparten nada salvo `hardware.json`, que solo se lee."""
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
                return None
            summary = summarize(json.loads((run / 'hardware.pnr').read_text()))
            (run / 'summary.json').write_text(json.dumps(summary, indent=2))
            return dict(seed=seed, clocks=summary['clocks'],
                        passes=timing_passes(summary['clocks']))

        # nextpnr es monohilo y con la misma semilla es determinista: correr
        # varias a la vez no cambia ningun resultado, solo el tiempo de pared.
        jobs = max(1, min(args.jobs, len(args.seeds)))
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            pending = [pool.submit(route, seed) for seed in args.seeds]
            for future in as_completed(pending):
                outcome = future.result()
                if outcome is None:
                    continue
                results.append(outcome)
                results.sort(key=lambda r: r['seed'])
                (folder / 'results.json').write_text(json.dumps(results, indent=2))
                cumple = outcome['passes']
                print(f"{_paint('OK', '32', color) if cumple else _paint('NO', '31', color)} "
                      f"seed {outcome['seed']}: "
                      + ', '.join(
                          f"{clock} {v['achieved']:.2f}/{v['constraint']:.0f} MHz"
                          for clock, v in sorted(outcome['clocks'].items()))
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
    mejor = best_seed(results)
    if mejor is not None:
        print(f'Más margen: semilla {mejor["seed"]} '
              f'({100 * (margin(mejor) - 1):+.1f} % en su reloj más justo)')
        # Cuando la mejor global no es la mejor en cada reloj, se ve aqui: p. ej.
        # dejar margen en el reloj de la CPU porque se va a tocar, y adoptar con
        # `--promote N` la que lo da.
        print('\n'.join(best_per_clock_lines(results, mejor['seed'], color)))
    else:
        print('Ninguna semilla cumple: aquí el problema ya no es la semilla.')
    if reference is not None:
        print('\n'.join(compare_sweeps(reference, results)))
    print(f'Informes: {folder}', flush=True)
    if args.promote is not None:
        wanted = mejor['seed'] if args.promote == 'best' and mejor else args.promote
        if mejor is None or wanted not in {r['seed'] for r in cumplen}:
            print('--promote: ' + ('ninguna semilla cumple' if mejor is None else
                  f'la semilla {wanted} no cumple timing') + '; no se toca el apio.ini.')
        else:
            adopted = promote_seed(prototype_dir, folder, wanted)
            print(f'Adoptada la semilla {wanted}: {adopted}')


if __name__ == '__main__':
    main()
