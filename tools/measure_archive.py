"""Archiva las medidas de `--measure` junto al build del RTL con que se hicieron.

Una medida de CPI solo vale para el RTL en que se tomo, y una propuesta para
subir Fmax se juzga por las dos cosas a la vez: un CPI peor puede compensar si
la frecuencia sube lo bastante. Por eso la medida se guarda en
`<prototipo>/reports/<fecha>-medida-<etiqueta>/` con:

  measure.json  los datos de cada caso, el hash de las fuentes sintetizables y
                el Fmax del build que corresponde a ESAS fuentes
  measure.md    la tabla de esa version

y `compare` pone dos medidas una junto a otra.

La metrica que junta CPI y frecuencia es `ns por instruccion = CPI / Fmax`. El
reloj real esta fijo (80 MHz, por el divisor de la UART), asi que el Fmax no
acelera nada hasta que se suba el reloj: es una PROYECCION a la frecuencia
maxima que el build alcanzo, no una medida.

Uso:
  python tools/measure_archive.py compare A B          carpetas o measure.json
  python tools/measure_archive.py compare --prototype 30   las dos ultimas
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_report import synthesizable_source_hashes  # noqa: E402
from tools.prototype import PrototypeResolutionError, resolve_prototype  # noqa: E402

MEASURE_JSON = 'measure.json'
MEASURE_MD = 'measure.md'


def limiting_clock(clocks):
    """(nombre, alcanzado, exigido) del reloj con menos margen, o None.

    El limite es el de menor `alcanzado / exigido`: en un prototipo con vídeo
    hay relojes de 25 y 125 MHz que no son el que manda en la CPU.
    """
    candidates = [(name, values['achieved'], values['constraint'])
                  for name, values in (clocks or {}).items()
                  if values.get('constraint')]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[1] / item[2])


def matching_build(prototype_dir):
    """(carpeta, summary) del build mas reciente hecho con las fuentes ACTUALES.

    Solo cuenta un build que termino bien y cuyo hash de fuentes es el de ahora:
    con otro RTL el Fmax no es el de lo que se ha medido.
    """
    current = synthesizable_source_hashes(prototype_dir)
    for metadata_path in sorted((prototype_dir / 'reports').glob('*/metadata.json'),
                                reverse=True):
        folder = metadata_path.parent
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        archived = {
            name: digest for name, digest in metadata.get('source_sha256', {}).items()
            if (name == 'apio.ini' or Path(name).suffix in {'.v', '.sv', '.vh', '.lpf'})
            and not Path(name).name.endswith('_tb.v')
        }
        if metadata.get('exit_code') == 0 and archived == current:
            return folder, summary
    return None


def pooled_cpi(cases):
    """CPI del conjunto: ciclos totales entre instrucciones totales.

    Solo con los casos que no son de tiempo real (video, UART): su numero de
    instrucciones depende del reloj o del baudrate y falsearia la media.
    """
    cycles = instructions = 0
    for data in cases.values():
        if data.get('skipped') or data.get('realtime'):
            continue
        if data.get('cycles') and data.get('instructions'):
            cycles += data['cycles']
            instructions += data['instructions']
    return cycles / instructions if instructions else None


def archive_measurement(prototype_dir, version, measurements, table, label,
                        realtime=(), now=None):
    """Escribe la medida de una version y devuelve la carpeta.

    `measurements` es `{caso: {instructions, cycles, clock_hz, stalls, video}}`
    (o `{skipped, reason}`); `video` es `{frames, swaps}` y solo lo llevan los
    casos de video. `table` es el Markdown de esa version, ya hecho.
    """
    now = now or datetime.now()
    safe = re.sub(r'[^A-Za-z0-9_-]', '_', label)
    folder = prototype_dir / 'reports' / (now.strftime('%Y%m%d-%H%M%S-%f') + '-medida-' + safe)
    folder.mkdir(parents=True)
    build = matching_build(prototype_dir)
    fmax = None
    if build is not None:
        clock = limiting_clock(build[1].get('clocks'))
        if clock is not None:
            fmax = dict(clock=clock[0], achieved_mhz=clock[1], constraint_mhz=clock[2],
                        build=build[0].name)
    cases = {name: dict(data, realtime=name in realtime)
             for name, data in measurements.items()}
    document = dict(
        version=version, label=label, created=now.isoformat(),
        source_sha256=synthesizable_source_hashes(prototype_dir),
        fmax=fmax, cpi=pooled_cpi(cases), cases=cases,
    )
    (folder / MEASURE_JSON).write_text(json.dumps(document, indent=2), encoding='utf-8')
    (folder / MEASURE_MD).write_text(table, encoding='utf-8')
    return folder


def load_measure(path):
    path = Path(path)
    return json.loads((path / MEASURE_JSON if path.is_dir() else path)
                      .read_text(encoding='utf-8'))


def newest_measures(prototype_dir, count=2):
    """Las `count` carpetas de medida mas recientes, de la mas nueva a la mas vieja."""
    return sorted((prototype_dir / 'reports').glob(f'*/{MEASURE_JSON}'),
                  reverse=True)[:count]


def ns_per_instruction(cpi, fmax):
    """ns por instruccion a la frecuencia maxima del build; None si falta algo."""
    if not cpi or not fmax or not fmax.get('achieved_mhz'):
        return None
    return 1000.0 * cpi / fmax['achieved_mhz']


def _cpi(data):
    if not data or data.get('skipped') or not data.get('instructions') or not data.get('cycles'):
        return None
    return data['cycles'] / data['instructions']


def _change(before, after):
    if before is None or after is None or before == 0:
        return 'n/d'
    return f'{100.0 * (after - before) / before:+.1f} %'


def compare_measures(before, after):
    """Texto que pone `before` y `after` uno junto a otro.

    Un numero MENOR de ns por instruccion es mejor. La mejora total sale de la
    proyeccion CPI / Fmax, que es donde se ve si un CPI peor compensa.
    """
    lines = []
    for name, doc in (('antes', before), ('despues', after)):
        fmax = doc.get('fmax')
        cpi = doc.get('cpi')
        ns = ns_per_instruction(cpi, fmax)
        cpi_text = 'n/d' if cpi is None else f'{cpi:.3f}'
        fmax_text = 'n/d' if not fmax else '{:.2f} MHz'.format(fmax['achieved_mhz'])
        ns_text = 'n/d' if ns is None else f'{ns:.2f}'
        lines.append(f"{name}: {doc.get('label')} ({doc.get('created', '')[:19]}) "
                     f"CPI {cpi_text}, Fmax {fmax_text}, {ns_text} ns/instr")
    if before.get('source_sha256') == after.get('source_sha256'):
        lines.append('AVISO: mismo RTL en las dos medidas; la diferencia es ruido o del programa.')
    cpi_b, cpi_a = before.get('cpi'), after.get('cpi')
    ns_b = ns_per_instruction(cpi_b, before.get('fmax'))
    ns_a = ns_per_instruction(cpi_a, after.get('fmax'))
    fmax_b = (before.get('fmax') or {}).get('achieved_mhz')
    fmax_a = (after.get('fmax') or {}).get('achieved_mhz')
    lines.append(f'CPI {_change(cpi_b, cpi_a)}; Fmax {_change(fmax_b, fmax_a)}; '
                 f'ns/instr {_change(ns_b, ns_a)} (proyeccion a Fmax)')
    lines += ['', '| Caso | CPI antes | CPI despues | Cambio |', '| --- | ---: | ---: | ---: |']
    shared = [name for name in before.get('cases', {}) if name in after.get('cases', {})]
    for name in shared:
        b, a = before['cases'][name], after['cases'][name]
        if b.get('realtime') or a.get('realtime'):
            continue
        cpi_before, cpi_after = _cpi(b), _cpi(a)
        if cpi_before is None and cpi_after is None:
            continue
        text_b = 'n/d' if cpi_before is None else f'{cpi_before:.2f}'
        text_a = 'n/d' if cpi_after is None else f'{cpi_after:.2f}'
        lines.append(f'| {name} | {text_b} | {text_a} | {_change(cpi_before, cpi_after)} |')
    lines += ['', 'Los casos de video y de UART no entran: sus instrucciones dependen del '
                  'reloj o del baudrate.']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    compare = sub.add_parser('compare', help='compara dos medidas')
    compare.add_argument('measures', nargs='*', metavar='MEDIDA',
                         help='carpeta o measure.json: primero la de antes, luego la de despues')
    compare.add_argument('-p', '--prototype',
                         help='compara las dos medidas mas recientes de este prototipo')
    args = parser.parse_args(argv)
    if args.prototype:
        try:
            directory = resolve_prototype(args.prototype, root=REPO_ROOT)
        except PrototypeResolutionError as error:
            print(f'error: {error}', file=sys.stderr)
            return 2
        found = newest_measures(directory)
        if len(found) < 2:
            print(f'{directory.name} tiene {len(found)} medida(s); hacen falta dos.',
                  file=sys.stderr)
            return 2
        paths = [found[1], found[0]]
    else:
        if len(args.measures) != 2:
            compare.error('hacen falta dos medidas (o --prototype)')
        paths = args.measures
    try:
        before, after = (load_measure(path) for path in paths)
    except (OSError, json.JSONDecodeError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    print(compare_measures(before, after), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
