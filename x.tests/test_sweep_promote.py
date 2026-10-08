import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'tools'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sweep_report  # noqa: E402
from tools.build_report import (  # noqa: E402
    bitstream_is_current, configured_options, configured_seed, synthesizable_source_hashes,
)

PASSING = {'clk': {'achieved': 110.0, 'constraint': 100.0}}


class PromoteSeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proto = Path(self.tmp.name) / '99.demo'
        self.proto.mkdir()
        (self.proto / 'top.v').write_text('module top; endmodule\n', encoding='utf-8')
        (self.proto / 'apio.ini').write_text(
            '[env:default]\nnextpnr-extra-options = --seed 9 --tmg-ripup\n', encoding='utf-8')
        self.build = self.proto / 'reports' / '20260101-000000-build'
        self.sweep = self.build / 'sweep-1'
        run = self.sweep / 'seed-9'
        run.mkdir(parents=True)
        for name, text in (('hardware.json', '{}'), ('scons.params', 'x'),
                           ('sources.zip', 'z')):
            (self.build / name).write_text(text)
        self.build.joinpath('metadata.json').write_text(json.dumps({
            'exit_code': 0, 'sources_changed_during_build': [],
            'source_sha256': synthesizable_source_hashes(self.proto)}))
        self.sweep.joinpath('metadata.json').write_text(json.dumps(
            {'nextpnr_options': ['tmg-ripup']}))
        for name in ('hardware.config', 'hardware.pnr', 'build.log'):
            (run / name).write_text(name)
        (run / 'exit_code.txt').write_text('0')
        (run / 'summary.json').write_text(json.dumps({'clocks': PASSING}))

    def promote(self, seed=9):
        def fake_ecppack(command, **_):
            Path(command[-1]).write_bytes(b'bit')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with mock.patch.object(sweep_report, 'find_oss_cad_suite', return_value=Path('suite')), \
                mock.patch.object(sweep_report, 'find_toolchain_binary', return_value=Path('ecppack')), \
                mock.patch.object(sweep_report, 'oss_cad_suite_env', return_value={}), \
                mock.patch.object(sweep_report.subprocess, 'run', side_effect=fake_ecppack):
            return sweep_report.promote_seed(self.proto, self.sweep, seed)

    def test_promote_archives_the_seed_and_leaves_a_current_bitstream(self):
        folder = self.promote()
        self.assertEqual((folder / 'hardware.bit').read_bytes(), b'bit')
        self.assertEqual((self.proto / '_build' / 'default' / 'hardware.bit').read_bytes(), b'bit')
        self.assertEqual(json.loads((folder / 'metadata.json').read_text())['exit_code'], 0)
        self.assertTrue(bitstream_is_current(self.proto))

    def test_adopts_another_seed_by_writing_it_into_apio_ini(self):
        shutil.copytree(self.sweep / 'seed-9', self.sweep / 'seed-3')
        self.promote(seed=3)
        self.assertEqual(configured_seed(self.proto), 3)
        self.assertTrue(bitstream_is_current(self.proto))
    def test_refuses_when_rtl_changed_since_the_swept_build(self):
        (self.proto / 'top.v').write_text('module top; wire x; endmodule\n', encoding='utf-8')
        with self.assertRaises(SystemExit) as caught:
            self.promote()
        self.assertIn('fuentes', str(caught.exception))

    def test_adopting_writes_the_options_the_seed_was_swept_with(self):
        (self.proto / 'apio.ini').write_text(
            '[env:default]\nnextpnr-extra-options = --seed 1\n', encoding='utf-8')
        self.promote()
        self.assertEqual(configured_seed(self.proto), 9)
        self.assertIn('--tmg-ripup', configured_options(self.proto))

    def test_apio_ini_is_restored_when_packing_fails(self):
        before = (self.proto / 'apio.ini').read_bytes()
        shutil.copytree(self.sweep / 'seed-9', self.sweep / 'seed-3')
        with mock.patch.object(sweep_report.subprocess, 'run',
                               return_value=SimpleNamespace(returncode=1, stdout='', stderr='x')), \
                mock.patch.object(sweep_report, 'find_oss_cad_suite', return_value=Path('suite')), \
                mock.patch.object(sweep_report, 'find_toolchain_binary', return_value=Path('e')), \
                mock.patch.object(sweep_report, 'oss_cad_suite_env', return_value={}):
            with self.assertRaises(SystemExit):
                sweep_report.promote_seed(self.proto, self.sweep, 3)
        self.assertEqual((self.proto / 'apio.ini').read_bytes(), before)
    def test_refuses_a_seed_that_fails_timing(self):
        (self.sweep / 'seed-9' / 'summary.json').write_text(json.dumps(
            {'clocks': {'clk': {'achieved': 90.0, 'constraint': 100.0}}}))
        with self.assertRaises(SystemExit):
            self.promote()

    def test_best_seed_and_per_clock_table(self):
        def res(seed, a, b):
            return dict(seed=seed, passes=True, clocks={
                'cpu': dict(achieved=a, constraint=80.0), 'sdram': dict(achieved=b, constraint=100.0)})
        results = [res(1, 90.0, 101.0), res(2, 82.0, 120.0), dict(res(3, 200.0, 99.0), passes=False)]
        self.assertEqual(sweep_report.best_seed(results)['seed'], 2)
        best = sweep_report.best_per_clock(results)
        self.assertEqual((best['cpu']['seed'], best['sdram']['seed']), (1, 2))
        lines = sweep_report.best_per_clock_lines(results, chosen=2, color=False)
        self.assertTrue(any('cpu' in l and 'semilla   1' in l and 'global' not in l for l in lines))
        self.assertTrue(any('sdram' in l and 'semilla   2' in l and 'global' in l for l in lines))
        self.assertEqual(sweep_report.best_per_clock_lines([res(1, 90.0, 120.0)], color=False), [])
        self.assertIsNone(sweep_report.best_seed([dict(res(3, 1.0, 1.0), passes=False)]))

if __name__ == '__main__':
    unittest.main()
