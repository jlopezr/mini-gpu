"""Retain seeded routing reports from a verified archived build.

Genérico: no depende de qué prototipo es. --report-dir es opcional: si se
omite, usa el último build archivado de --prototype con summary.json."""
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
    if not timing_passes(original.get('fmax', {})):
        raise SystemExit('Source build does not pass timing.')
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
            if result.returncode:
                raise SystemExit(f'Seed {seed} failed; retained {run}')
            summary = summarize(json.loads((run / 'hardware.pnr').read_text()))
            (run / 'summary.json').write_text(json.dumps(summary, indent=2))
            if not timing_passes(summary['clocks']):
                raise SystemExit(f'Seed {seed} failed timing; retained {run}')
            results.append(dict(seed=seed, clocks=summary['clocks']))
            (folder / 'results.json').write_text(json.dumps(results, indent=2))
            print(results[-1], flush=True)
    medians = {clock: statistics.median(r['clocks'][clock]['achieved'] for r in results)
               for clock in results[0]['clocks']}
    (folder / 'medians.json').write_text(json.dumps(medians, indent=2))
    print(f'Medians: {medians}; reports: {folder}', flush=True)


if __name__ == '__main__':
    main()
