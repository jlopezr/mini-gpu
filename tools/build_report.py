"""Run Apio once, stream PNR progress, and retain reproducible timing history.

Genérico: no depende de qué prototipo es, solo de en qué carpeta corre. Cada
prototipo con apio.ini puede usarlo con --prototype, sin copiarlo."""
import argparse
from collections import defaultdict
import configparser
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from tools.prototype import PrototypeResolutionError, find_apio_binary, find_repo_root, resolve_prototype


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


def default_env(prototype_dir):
    """Env que usa `apio build` sin -e, que es donde deja _build/<env>/.

    No siempre se llama 'default': 13.hdmi arranca en 'colour-cycle'. Tenerlo
    escrito a mano hacia que el informe de timing se buscara en una carpeta que
    no existe, y el build acababa en 'Missing timing report' pese a haber
    sintetizado y cerrado el timing sin problemas.
    """
    config = configparser.ConfigParser()
    try:
        config.read(prototype_dir / 'apio.ini', encoding='utf-8')
        return config.get('apio', 'default-env', fallback='default')
    except (configparser.Error, OSError):
        return 'default'


def configured_seed(prototype_dir):
    """Seed fixed for the environment used by plain ``apio build``."""
    config = configparser.ConfigParser()
    try:
        config.read(prototype_dir / 'apio.ini', encoding='utf-8')
        env = default_env(prototype_dir)
        env_section = f'env:{env}'
        if config.has_option(env_section, 'nextpnr-extra-options'):
            options = config.get(env_section, 'nextpnr-extra-options')
        else:
            options = config.get('common', 'nextpnr-extra-options', fallback='')
    except (configparser.Error, OSError):
        return None
    match = re.search(r'(?:^|\s)--seed(?:\s+|=)(\d+)(?:\s|$)', options)
    return int(match.group(1)) if match else None


def nextpnr_flags(items):
    """`tmg-ripup placer-heap-timingweight=30` -> ['--tmg-ripup', '--placer-heap-timingweight', '30'].

    Sin guiones y con `=` para que argparse no las tome por opciones propias y
    para que no dependan de como cite cada shell.
    """
    flags = []
    for item in items:
        name, _, value = item.lstrip('-').partition('=')
        if name in ('seed', 'json', 'report', 'lpf', 'textcfg', 'package', 'speed', 'force'):
            raise SystemExit(f'--nextpnr-options no puede llevar "{name}": ya lo pone el barrido.')
        flags += [f'--{name}', *([value] if value else [])]
    return flags


def merge_nextpnr_flags(value, flags):
    """Deja en `value` (texto de nextpnr-extra-options) las banderas de `flags`.

    Las que ya estaban con el mismo nombre se sustituyen, con o sin valor.
    """
    names = {flag.split('=', 1)[0] for flag in flags if flag.startswith('--')}
    tokens = value.split()
    kept = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token.startswith('--') and token.split('=', 1)[0] in names:
            if '=' not in token and index < len(tokens) and not tokens[index].startswith('--'):
                index += 1
            continue
        kept.append(token)
    return ' '.join(kept + list(flags))


def set_configured_seed(prototype_dir, seed, options=()):
    """Write ``--seed N`` into the nextpnr options that ``configured_seed`` reads.

    Edits the line in place (comments and line endings stay), replacing an
    existing ``--seed`` or appending one. ``options`` son opciones extra de
    nextpnr en el formato de ``nextpnr_flags``, con las que se eligio la
    semilla: una semilla solo vale con las opciones con las que se midio.
    Returns the previous seed.
    """
    flags = nextpnr_flags(options)
    path = prototype_dir / 'apio.ini'
    previous = configured_seed(prototype_dir)
    lines = path.read_bytes().decode('utf-8').splitlines(keepends=True)
    option = re.compile(r'^(\s*nextpnr-extra-options\s*=)(.*?)(\r?\n?)$')
    found = {}
    section = None
    for index, line in enumerate(lines):
        header = re.match(r'^\s*\[([^\]]+)\]', line)
        if header:
            section = header.group(1)
        elif option.match(line):
            found.setdefault(section, index)
    env_section = f'env:{default_env(prototype_dir)}'
    target = found.get(env_section, found.get('common'))
    if target is None:
        # Sin la opción en ningún sitio: se crea al final de la sección del entorno.
        start = next((i for i, line in enumerate(lines)
                      if re.match(rf'^\s*\[{re.escape(env_section)}\]', line)), None)
        if start is None:
            raise SystemExit(f'{path} no tiene la seccion [{env_section}]; anade --seed {seed} a mano.')
        end = next((i for i in range(start + 1, len(lines))
                    if re.match(r'^\s*\[', lines[i])), len(lines))
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        newline = '\r\n' if lines[start].endswith('\r\n') else '\n'
        if not lines[end - 1].endswith(('\n', '\r')):
            lines[end - 1] += newline
        lines.insert(end, 'nextpnr-extra-options = '
                          + merge_nextpnr_flags(f'--seed {seed}', flags) + newline)
        path.write_text(''.join(lines), encoding='utf-8', newline='')
        return previous
    head, value, newline = option.match(lines[target]).groups()
    seed_re = re.compile(r'(^|\s)--seed(?:\s+|=)\d+(?=\s|$)')
    if seed_re.search(value):
        value = seed_re.sub(lambda m: f'{m.group(1)}--seed {seed}', value, count=1)
    else:
        value = f'{value.rstrip()} --seed {seed}' if value.strip() else f' --seed {seed}'
    if flags:
        value = ' ' + merge_nextpnr_flags(value, flags)
    lines[target] = f'{head}{value}{newline}'
    path.write_text(''.join(lines), encoding='utf-8', newline='')
    return previous


def synthesizable_source_hashes(prototype_dir):
    """Hashes used to decide whether the local bitstream matches the RTL."""
    paths = [
        *prototype_dir.glob('*.v'), *prototype_dir.glob('*.sv'),
        *prototype_dir.glob('*.vh'), *prototype_dir.glob('*.lpf'),
        *prototype_dir.glob('sim/*.vh'), prototype_dir / 'apio.ini',
    ]
    paths = [path for path in paths
             if path.is_file() and not path.name.endswith('_tb.v')]
    return {
        str(path.relative_to(prototype_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def bitstream_is_current(prototype_dir):
    """Whether hardware.bit represents the current synthesizable sources.

    A successful cached Apio build may deliberately preserve hardware.bit's
    old mtime. Prefer the reproducible source hashes archived by build_report;
    use mtimes only for old builds that predate that metadata.
    """
    bitstream = prototype_dir / '_build' / default_env(prototype_dir) / 'hardware.bit'
    if not bitstream.is_file():
        return False
    reports = sorted((prototype_dir / 'reports').glob('*/metadata.json'), reverse=True)
    if reports:
        try:
            metadata = json.loads(reports[0].read_text(encoding='utf-8'))
            archived = metadata.get('source_sha256', {})
            relevant = {
                name: digest for name, digest in archived.items()
                if (name == 'apio.ini' or Path(name).suffix in {'.v', '.sv', '.vh', '.lpf'})
                and not Path(name).name.endswith('_tb.v')
            }
            if metadata.get('exit_code') == 0 and relevant:
                return relevant == synthesizable_source_hashes(prototype_dir)
        except (OSError, json.JSONDecodeError):
            pass
    built_at = bitstream.stat().st_mtime
    return all(path.stat().st_mtime <= built_at for path in [
        *prototype_dir.glob('*.v'), *prototype_dir.glob('*.sv'),
        *prototype_dir.glob('*.vh'), *prototype_dir.glob('*.lpf'),
        prototype_dir / 'apio.ini',
    ] if path.is_file() and not path.name.endswith('_tb.v'))


def _metadata_source_hashes(metadata):
    return {
        name: digest for name, digest in metadata.get('source_sha256', {}).items()
        if (name == 'apio.ini' or Path(name).suffix in {'.v', '.sv', '.vh', '.lpf'})
        and not Path(name).name.endswith('_tb.v')
    }


def reusable_detailed_report(prototype_dir):
    """Newest detailed report that exactly matches the current RTL, if any."""
    if not bitstream_is_current(prototype_dir):
        return None
    current = synthesizable_source_hashes(prototype_dir)
    for metadata_path in sorted(
            (prototype_dir / 'reports').glob('*/metadata.json'), reverse=True):
        folder = metadata_path.parent
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if (metadata.get('exit_code') == 0
                and metadata.get('incremental') is False
                and _metadata_source_hashes(metadata) == current
                and all((folder / name).is_file()
                        for name in ('build.log', 'hardware.pnr', 'summary.json'))):
            return folder
    return None


def timing_passes(clocks):
    return bool(clocks) and all(v['achieved'] >= v['constraint']
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
    parser.add_argument('-p', '--prototype', required=True)
    parser.add_argument('--label', default='build')
    parser.add_argument('--archive-only', action='store_true',
                        help='Archive existing outputs; does not run Apio.')
    cache_mode = parser.add_mutually_exclusive_group()
    cache_mode.add_argument('--incremental', dest='incremental', action='store_true',
                            help='Force a run using normal Apio caching.')
    cache_mode.add_argument('--no-incremental', dest='incremental', action='store_false',
                            help='Force detailed PNR progress and regenerate routing.')
    parser.set_defaults(incremental=None)
    args = parser.parse_args()
    repo_root = find_repo_root(Path.cwd())
    try:
        ROOT = resolve_prototype(args.prototype, root=repo_root)
    except PrototypeResolutionError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(f'Using prototype: {ROOT.name}')
    label = re.sub(r'[^A-Za-z0-9_-]', '_', args.label)
    # Apio clean removes all of _build. Keep the history outside that tree.
    history = ROOT / 'reports'
    previous = sorted(history.glob('*/summary.json'))
    if not args.archive_only and args.incremental is None:
        reusable = reusable_detailed_report(ROOT)
        if reusable is not None:
            print(f'Reports: {reusable}', flush=True)
            print(f'RTL and build options unchanged; reusing detailed report: {reusable}')
            summary = json.loads((reusable / 'summary.json').read_text(encoding='utf-8'))
            return 0 if timing_passes(summary.get('clocks', {})) else 1
    folder = history / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + label)
    folder.mkdir(parents=True)
    hashes = {}
    # Apio searches recursively for constraints. A ZIP avoids treating archived
    # LPF/RTL files as additional project inputs on the next build.
    with zipfile.ZipFile(folder / 'sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for pattern in ('*.v', '*.sv', '*.vh', '*.ini', '*.lpf', '*.ps1', '*.py', 'sim/*.vh'):
            for src in ROOT.glob(pattern):
                relative = src.relative_to(ROOT)
                data = src.read_bytes()
                archive.writestr(str(relative), data)
                hashes[str(relative)] = hashlib.sha256(data).hexdigest()
    command = [find_apio_binary(ROOT.parent), 'build', '-p', str(ROOT)]
    detailed = args.incremental is not True
    if detailed:
        command.append('--verbose-pnr')
    metadata = dict(label=args.label, archive_only=args.archive_only,
                    incremental=not detailed,
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
        src = ROOT / '_build' / default_env(ROOT) / name
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
        if not detailed:
            print('Incremental mode: live routing progress and slack histograms are not requested.')
    print(f'Detailed timing: {report_path}')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
