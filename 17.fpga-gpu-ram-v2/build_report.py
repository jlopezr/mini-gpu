"""Run Apio once, stream PNR progress, and retain reproducible timing history."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parent


def extract_log_details(folder):
    log = folder / 'build.log'
    if not log.exists():
        return
    histograms, histogram, rows = [], [], []
    for line in log.read_text(encoding='utf-8').splitlines():
        if 'Slack histogram:' in line:
            if histogram:
                histograms.append('\n'.join(histogram))
            histogram = [line]
        elif histogram:
            if not line.strip():
                continue
            if 'legend:' in line or 'represents' in line or re.match(r'\s*\[\s*-?\d+,', line):
                histogram.append(line)
            else:
                histograms.append('\n'.join(histogram))
                histogram = []
        match = re.match(
            r'\s*(\d+)\s*\|\s*(\d+)\s+(\d+)\s*\|\s*(\d+)\s+(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s+([\d.]+)\s*\|', line)
        if match:
            rows.append(match.groups())
    if histogram:
        histograms.append('\n'.join(histogram))
    if histograms:
        (folder / 'slack_histograms.txt').write_text('\n\n'.join(histograms) + '\n', encoding='utf-8')
    if rows:
        with (folder / 'routing_progress.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['iteration', 'with_ripup', 'without_ripup',
                             'delta_with_ripup', 'delta_without_ripup',
                             'remaining_arcs', 'batch_seconds', 'total_seconds'])
            writer.writerows(rows)


def timing_passes(clocks):
    return bool(clocks) and all(v['constraint'] >= 25 and
                               v['achieved'] >= v['constraint']
                               for v in clocks.values())


def summarize(report):
    paths = []
    for item in report.get('critical_paths', []):
        segments = item.get('path', [])
        delays = defaultdict(float)
        for segment in segments:
            delays[segment['type']] += segment['delay']
        paths.append(dict(
            source=item.get('from'), destination=item.get('to'),
            delay_ns=sum(delays.values()), segments=len(segments),
            delay_by_type=dict(delays),
            first=segments[0].get('from') if segments else None,
            last=segments[-1].get('to') if segments else None,
            nets=[s['net'] for s in segments if 'net' in s],
        ))
    return dict(clocks=report.get('fmax', {}),
                utilization=report.get('utilization', {}), paths=paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', default='build')
    parser.add_argument('--archive-only', action='store_true',
                        help='Archive existing outputs; does not run Apio.')
    parser.add_argument('--incremental', action='store_true',
                        help='Use normal Apio caching; suppresses live PNR progress.')
    args = parser.parse_args()
    label = re.sub(r'[^A-Za-z0-9_-]', '_', args.label)
    # Apio clean removes all of _build. Keep the history outside that tree.
    history = ROOT / 'reports'
    previous = sorted(history.glob('*/summary.json'))
    folder = history / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + label)
    folder.mkdir(parents=True)
    hashes = {}
    # Apio searches recursively for constraints. A ZIP avoids treating archived
    # LPF/RTL files as additional project inputs on the next build.
    with zipfile.ZipFile(folder / 'sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for pattern in ('*.v', '*.ini', '*.lpf', '*.ps1', '*.py', 'sim/*.vh'):
            for src in ROOT.glob(pattern):
                relative = src.relative_to(ROOT)
                data = src.read_bytes()
                archive.writestr(str(relative), data)
                hashes[str(relative)] = hashlib.sha256(data).hexdigest()
    command = [str(ROOT.parent / '.venv/Scripts/apio.exe'), 'build', '-p', str(ROOT)]
    if not args.incremental:
        command.append('--verbose-pnr')
    metadata = dict(label=args.label, archive_only=args.archive_only,
                    incremental=args.incremental,
                    command=command, source_sha256=hashes,
                    started=datetime.now().isoformat())
    if args.archive_only:
        metadata['notice'] = 'Existing outputs: source snapshot is current, not proof of the sources used to build them.'
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(f'Reports: {folder}', flush=True)
    started = time.monotonic()
    result = 0
    if not args.archive_only:
        with (folder / 'build.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, cwd=ROOT,
                                       text=True, encoding='utf-8', errors='replace')
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)
            result = process.wait()
        extract_log_details(folder)
    changed = [name for name, digest in hashes.items()
               if not (ROOT / name).exists() or
               hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    metadata.update(exit_code=result, elapsed_seconds=time.monotonic() - started,
                    sources_changed_during_build=changed)
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    # Preserve outputs even on failure, but never present stale timing as success.
    for name in ('hardware.pnr', 'hardware.json', 'hardware.config', 'hardware.bit', 'scons.params'):
        src = ROOT / '_build/default' / name
        if src.exists():
            shutil.copy2(src, folder / name)
    if result:
        print('Build failed; archived outputs may predate this attempt.')
        return result
    report_path = folder / 'hardware.pnr'
    if not report_path.exists():
        print('Missing timing report.')
        return 1
    report = json.loads(report_path.read_text())
    summary = summarize(report)
    summary.update(label=args.label, archive_only=args.archive_only,
                   elapsed_seconds=metadata['elapsed_seconds'])
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    lines = [f'Label: {args.label}', f'Elapsed: {metadata["elapsed_seconds"]:.1f} s']
    if changed:
        lines.append('Sources changed during build: ' + ', '.join(changed))
    old = json.loads(previous[-1].read_text()) if previous else {}
    passed = timing_passes(summary['clocks'])
    for clock, values in summary['clocks'].items():
        achieved, constraint = values['achieved'], values['constraint']
        line = f'{clock}: {achieved:.2f} MHz; required {constraint:.2f} MHz'
        prior = old.get('clocks', {}).get(clock)
        if prior:
            line += f'; previous {prior["achieved"]:.2f} MHz (single run, not statistical evidence)'
        lines.append(line)
    for index, path in enumerate(summary['paths']):
        lines.append(f'Path {index}: {path["delay_ns"]:.3f} ns; {path["segments"]} segments; {path["delay_by_type"]}')
        lines.extend('  ' + net for net in path['nets'])
    for name, values in summary['utilization'].items():
        lines.append(f'{name}: {values["used"]} / {values["available"]}')
    text = '\n'.join(lines) + '\n'
    (folder / 'summary.txt').write_text(text, encoding='utf-8')
    print(text)
    if not args.archive_only:
        print(f'Build log: {folder / "build.log"}')
        if args.incremental:
            print('Incremental mode: live routing progress and slack histograms are not requested.')
    print(f'Detailed timing: {report_path}')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
