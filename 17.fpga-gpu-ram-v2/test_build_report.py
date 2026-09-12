import unittest
import csv
from pathlib import Path
import tempfile
from unittest.mock import patch, MagicMock
import io
import json
import zipfile

from build_report import extract_log_details, main, summarize, timing_passes


class BuildReportTest(unittest.TestCase):
    def test_incremental_build_archives_without_exposing_constraints(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'project'
            output = root / '_build/default'
            output.mkdir(parents=True)
            (root / 'board.lpf').write_text('constraint')
            (output / 'hardware.pnr').write_text(json.dumps({
                'fmax': {'clk': {'constraint': 25, 'achieved': 40}},
            }))
            process = MagicMock()
            process.stdout = iter(['cached build\n'])
            process.wait.return_value = 0
            with patch('build_report.ROOT', root), patch('sys.argv', ['build_report', '--incremental']), \
                 patch('build_report.subprocess.Popen', return_value=process) as launch, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 0)
            self.assertNotIn('--verbose-pnr', launch.call_args.args[0])
            folder = next((root / 'reports').iterdir())
            self.assertEqual(list(folder.rglob('*.lpf')), [])
            with zipfile.ZipFile(folder / 'sources.zip') as archive:
                self.assertEqual(archive.read('board.lpf'), b'constraint')
            self.assertTrue((folder / 'summary.json').exists())

    def test_failed_build_does_not_summarize_stale_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / '_build/default'
            output.mkdir(parents=True)
            (output / 'hardware.pnr').write_text('{"fmax":{"clk":{"constraint":25,"achieved":40}}}')
            process = MagicMock()
            process.stdout = iter(['failed\n'])
            process.wait.return_value = 1
            with patch('build_report.ROOT', root), patch('sys.argv', ['build_report']), \
                 patch('build_report.subprocess.Popen', return_value=process), \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 1)
            self.assertFalse(list((root / 'reports').glob('*/summary.json')))

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
        self.assertFalse(timing_passes({'clk': {'constraint': 24, 'achieved': 37}}))
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
