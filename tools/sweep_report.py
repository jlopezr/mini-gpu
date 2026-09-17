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
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile
from build_report import extract_log_details, summarize, timing_passes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import (
    PrototypeResolutionError, find_repo_root, find_toolchain_binary,
    oss_cad_suite_env, read_ecp5_params, resolve_prototype,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-p', '--prototype', required=True)
    parser.add_argument('--report-dir', type=Path, default=None)
    parser.add_argument('--seeds', type=int, nargs='+', default=[1, 2, 3, 4, 5])
    args = parser.parse_args()
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
        seeds=args.seeds, tool_sha256=hashlib.sha256(exe.read_bytes()).hexdigest()), indent=2))
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
                '--seed', str(seed), '--json', str(source / 'hardware.json'),
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
            print(f"{'OK ' if cumple else 'NO '} seed {seed}: "
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
    print(f'\nCumplen {len(cumplen)} de {len(results)}')
    for clock in sorted(results[0]['clocks']):
        valores = [r['clocks'][clock]['achieved'] for r in results]
        exigido = results[0]['clocks'][clock]['constraint']
        print(f'  {clock}: {min(valores):.2f} a {max(valores):.2f} MHz, '
              f'mediana {medians[clock]:.2f}, exigidos {exigido:.0f}')
    if cumplen:
        limitante = lambda r: min(  # noqa: E731 - el reloj con menos margen
            v['achieved'] / v['constraint'] for v in r['clocks'].values())
        mejor = max(cumplen, key=limitante)
        print(f'Más margen: semilla {mejor["seed"]} '
              f'({100 * (limitante(mejor) - 1):+.1f} % en su reloj más justo)')
    else:
        print('Ninguna semilla cumple: aquí el problema ya no es la semilla.')
    print(f'Informes: {folder}', flush=True)


if __name__ == '__main__':
    main()
