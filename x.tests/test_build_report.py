import unittest
import csv
from pathlib import Path
import tempfile
from unittest.mock import patch, MagicMock
import io
import json
import zipfile

from tools.build_report import (configured_seed, extract_log_details, main,
                                nextpnr_flags, set_configured_seed, summarize, synthesizable_source_hashes,
                                timing_passes)


class BuildReportTest(unittest.TestCase):
    def test_configured_seed_uses_the_default_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'apio.ini').write_text(
                '[apio]\ndefault-env = chosen\n[common]\n'
                'nextpnr-extra-options = --seed 3\n[env:chosen]\n'
                'nextpnr-extra-options = --detailed-timing-report --seed=7\n',
                encoding='utf-8')
            self.assertEqual(configured_seed(root), 7)

    def test_set_configured_seed_replaces_or_appends_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ini = root / 'apio.ini'
            ini.write_text(
                '# nota\r\n[apio]\r\ndefault-env = chosen\r\n[env:other]\r\n'
                'nextpnr-extra-options = --seed 1\r\n[env:chosen]\r\n'
                'nextpnr-extra-options = --detailed-timing-report --seed 3\r\n',
                encoding='utf-8', newline='')
            self.assertEqual(set_configured_seed(root, 9), 3)
            self.assertEqual(configured_seed(root), 9)
            text = ini.read_bytes().decode()
            self.assertIn('[env:other]\r\nnextpnr-extra-options = --seed 1\r\n', text)
            self.assertIn('--detailed-timing-report --seed 9\r\n', text)
            ini.write_text('[env:chosen]\nnextpnr-extra-options = --foo\n', encoding='utf-8')
            (root / 'apio.ini').write_text(
                '[apio]\ndefault-env = chosen\n[env:chosen]\nnextpnr-extra-options = --foo\n',
                encoding='utf-8')
            self.assertIsNone(set_configured_seed(root, 2))
            self.assertEqual(configured_seed(root), 2)

    def test_set_configured_seed_writes_the_options_the_seed_was_measured_with(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ini = root / 'apio.ini'
            ini.write_text(
                '[env:default]\nboard = x\n'
                'nextpnr-extra-options = --detailed-timing-report --placer-heap-timingweight 30 --seed 2\n',
                encoding='utf-8')
            set_configured_seed(root, 5, ['tmg-ripup', 'placer-heap-timingweight=120'])
            options = ini.read_text().split('nextpnr-extra-options =')[1].split()
            self.assertEqual(options.count('--placer-heap-timingweight'), 1)
            self.assertEqual(options[options.index('--placer-heap-timingweight') + 1], '120')
            self.assertIn('--tmg-ripup', options)
            self.assertIn('--detailed-timing-report', options)
            self.assertEqual(configured_seed(root), 5)
            # Sin opciones, la linea conserva las que tenia.
            set_configured_seed(root, 6)
            self.assertIn('--tmg-ripup', ini.read_text())
            # Y si la opcion no existia en el fichero, se crea con ellas.
            ini.write_text('[env:default]\nboard = x\n', encoding='utf-8')
            set_configured_seed(root, 3, ['tmg-ripup'])
            self.assertIn('nextpnr-extra-options = --seed 3 --tmg-ripup', ini.read_text())

    def test_nextpnr_flags_reject_what_the_sweep_already_sets(self):
        self.assertEqual(nextpnr_flags(['router=router1', 'no-tmdriv']),
                         ['--router', 'router1', '--no-tmdriv'])
        for forbidden in ('seed=3', 'json=x', 'force'):
            with self.assertRaises(SystemExit):
                nextpnr_flags([forbidden])

    def test_set_configured_seed_creates_the_option_when_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ini = root / 'apio.ini'
            ini.write_text('[env:default]\r\nboard = x\r\ntop-module = top\r\n\r\n[env:other]\r\nboard = y',
                           encoding='utf-8', newline='')
            self.assertIsNone(set_configured_seed(root, 4))
            self.assertEqual(configured_seed(root), 4)
            self.assertEqual(
                ini.read_bytes().decode(),
                '[env:default]\r\nboard = x\r\ntop-module = top\r\n'
                'nextpnr-extra-options = --seed 4\r\n\r\n[env:other]\r\nboard = y')
            ini.write_text('[env:default]\nboard = x', encoding='utf-8', newline='')
            set_configured_seed(root, 7)
            self.assertEqual(ini.read_bytes().decode(),
                             '[env:default]\nboard = x\nnextpnr-extra-options = --seed 7\n')

    def test_default_build_uses_cache_and_archives_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'project'
            output = root / '_build/default'
            output.mkdir(parents=True)
            (root / 'board.lpf').write_text('constraint')
            (root / 'params.vh').write_text('`define WIDTH 8\n')
            (root / 'top.sv').write_text('module top; endmodule\n')
            (output / 'hardware.pnr').write_text(json.dumps({
                'fmax': {'clk': {'constraint': 25, 'achieved': 40}},
            }))
            process = MagicMock()
            process.stdout = iter(['cached build\n'])
            process.wait.return_value = 0
            with patch('tools.build_report.resolve_prototype', return_value=root), \
                 patch('sys.argv', ['build_report', '--prototype', 'project']), \
                 patch('tools.build_report.subprocess.Popen', return_value=process) as launch, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 0)
            self.assertIn('--verbose-pnr', launch.call_args.args[0])
            folder = next((root / 'reports').iterdir())
            self.assertEqual(list(folder.rglob('*.lpf')), [])
            with zipfile.ZipFile(folder / 'sources.zip') as archive:
                self.assertEqual(archive.read('board.lpf'), b'constraint')
                self.assertEqual(archive.read('params.vh'), (root / 'params.vh').read_bytes())
            metadata = json.loads((folder / 'metadata.json').read_text())
            self.assertIn('params.vh', metadata['source_sha256'])
            self.assertEqual(metadata['source_sha256'], synthesizable_source_hashes(root))
            self.assertIn('top.sv', metadata['source_sha256'])
            self.assertTrue((folder / 'summary.json').exists())

    def test_default_reuses_matching_detailed_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'project'
            root.mkdir()
            (root / 'apio.ini').write_text('[env:default]\nboard = ulx3s-85f\n')
            (root / 'top.v').write_text('module top; endmodule\n')
            output = root / '_build/default'
            output.mkdir(parents=True)
            (output / 'hardware.bit').write_bytes(b'bitstream')
            report = root / 'reports/20260929-120000-000000-build'
            report.mkdir(parents=True)
            metadata = {
                'incremental': False,
                'exit_code': 0,
                'source_sha256': synthesizable_source_hashes(root),
            }
            (report / 'metadata.json').write_text(json.dumps(metadata))
            (report / 'build.log').write_text('detailed routing log\n')
            (report / 'hardware.pnr').write_text('{}')
            (report / 'summary.json').write_text(json.dumps({
                'clocks': {'clk': {'constraint': 25, 'achieved': 40}},
            }))
            with patch('tools.build_report.resolve_prototype', return_value=root), \
                 patch('sys.argv', ['build_report', '--prototype', 'project']), \
                 patch('tools.build_report.subprocess.Popen') as launch, \
                 patch('sys.stdout', new_callable=io.StringIO) as output_text:
                self.assertEqual(main(), 0)
            launch.assert_not_called()
            self.assertIn('reusing detailed report', output_text.getvalue())
            self.assertEqual(len(list((root / 'reports').iterdir())), 1)

    def test_failed_build_does_not_summarize_stale_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / '_build/default'
            output.mkdir(parents=True)
            (output / 'hardware.pnr').write_text('{"fmax":{"clk":{"constraint":25,"achieved":40}}}')
            process = MagicMock()
            process.stdout = iter(['failed\n'])
            process.wait.return_value = 1
            with patch('tools.build_report.resolve_prototype', return_value=root), \
                 patch('sys.argv', ['build_report', '--prototype', 'project']), \
                 patch('tools.build_report.subprocess.Popen', return_value=process), \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 1)
            self.assertFalse(list((root / 'reports').glob('*/summary.json')))

    def test_no_incremental_requests_detailed_pnr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process = MagicMock()
            process.stdout = iter(['failed\n'])
            process.wait.return_value = 1
            with patch('tools.build_report.resolve_prototype', return_value=root), \
                 patch('sys.argv', ['build_report', '--prototype', 'project',
                                    '--no-incremental']), \
                 patch('tools.build_report.subprocess.Popen', return_value=process) as launch, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 1)
            self.assertIn('--verbose-pnr', launch.call_args.args[0])

    def test_extracts_native_progress_and_negative_slack(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'build.log').write_text(
                'Slack histogram:\n legend: * represents 63 endpoint(s)\n'
                '         + represents [1,63) endpoint(s)\n'
                '[ -1000,  2000) |****+\nChecksum: 0x123\n'
                ' 1000 | 94 905 | 94 905 | 125767| 1.35 1.35|\n'
                'Slack histogram:\n[ 2000, 3000) |**+\n', encoding='utf-8')
            extract_log_details(folder)
            histograms = (folder / 'slack_histograms.txt').read_text()
            self.assertEqual(histograms.count('Slack histogram:'), 2)
            self.assertIn('-1000', histograms)
            self.assertNotIn('Checksum', histograms)
            with (folder / 'routing_progress.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]['remaining_arcs'], '125767')

    def test_all_clock_domains_must_pass(self):
        self.assertTrue(timing_passes({'clk': {'constraint': 25, 'achieved': 37}}))
        self.assertFalse(timing_passes({}))
        self.assertTrue(timing_passes({
            'internal': {'constraint': 19.38, 'achieved': 153.85},
        }))
        self.assertFalse(timing_passes({
            'clk': {'constraint': 25, 'achieved': 37},
            'fast': {'constraint': 100, 'achieved': 99},
        }))

    def test_path_keeps_routing_separate_and_preserves_endpoints(self):
        start, end = {'cell': 'pc', 'port': 'Q'}, {'cell': 'next_pc', 'port': 'D'}
        report = {'critical_paths': [{'from': 'clk', 'to': 'clk', 'path': [
            {'type': 'clk-to-q', 'delay': .5, 'from': start, 'to': start},
            {'type': 'routing', 'delay': 2, 'net': 'selected_pc'},
            {'type': 'logic', 'delay': .25},
            {'type': 'setup', 'delay': .1, 'to': end},
        ]}]}
        path = summarize(report)['paths'][0]
        self.assertAlmostEqual(path['delay_ns'], 2.85)
        self.assertEqual(path['delay_by_type']['routing'], 2)
        self.assertEqual(path['segments'], 4)
        self.assertEqual(path['nets'], ['selected_pc'])
        self.assertEqual((path['first'], path['last']), (start, end))


if __name__ == '__main__':
    unittest.main()
