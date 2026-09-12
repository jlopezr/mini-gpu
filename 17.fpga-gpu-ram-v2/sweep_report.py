"""Retain seeded routing reports from a verified archived build."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import zipfile
from build_report import extract_log_details, summarize, timing_passes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[1, 2, 3, 4, 5])
    args = parser.parse_args()
    source = args.report_dir.resolve()
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
    suite = Path.home() / '.apio/packages/oss-cad-suite'
    exe = suite / 'bin/nextpnr-ecp5.exe'
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join(str(suite / part) for part in ('bin', 'lib', 'py3bin')) + os.pathsep + env.get('PATH', '')
    hashes = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
              for name in ('hardware.json', 'sources.zip')}
    (folder / 'metadata.json').write_text(json.dumps(dict(source=str(source), sha256=hashes,
        seeds=args.seeds, tool_sha256=hashlib.sha256(exe.read_bytes()).hexdigest()), indent=2))
    shutil.copy2(__file__, folder / 'sweep_report.py')
    results = []
    # Only the archived constraint is extracted, outside Apio's recursive tree.
    with tempfile.TemporaryDirectory(prefix='gpu-sweep-') as temporary:
        lpf = Path(temporary) / 'ulx3s_v20.lpf'
        with zipfile.ZipFile(source / 'sources.zip') as archive:
            lpf.write_bytes(archive.read('ulx3s_v20.lpf'))
        for seed in args.seeds:
            run = folder / f'seed-{seed}'
            run.mkdir()
            command = [str(exe), '--85k', '--package', 'CABGA381', '--speed', '6',
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
