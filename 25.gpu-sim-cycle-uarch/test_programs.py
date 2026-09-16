"""Real application kernels, compared against the independent GPU evaluator."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest
from dataclasses import asdict

from test_pipeline import ROOT, assemble_bytes, architecture
from cycle_sim import Pipeline, Config, functional


class ProgramTests(unittest.TestCase):
    def compare(self, source, name):
        image = assemble_bytes(source)
        oracle = functional.System(2 * 1024 * 1024)
        oracle.load_program(image)
        gpu = functional.System(2 * 1024 * 1024)
        gpu.load_program(image)
        pipeline = Pipeline(gpu, Config())
        oracle.run(1000000)
        pipeline.run(5000000)
        self.assertFalse(gpu.error)
        self.assertEqual(architecture(gpu), architecture(oracle))
        report = pipeline.counters.report()
        report.update(program=name, program_sha256=hashlib.sha256(image).hexdigest(),
                      memory_sha256=hashlib.sha256(gpu.memory).hexdigest(),
                      architectural_match=True, config=asdict(pipeline.config))
        if os.environ.get('MINIGPU_REPORT_DIR'):
            target = Path(os.environ['MINIGPU_REPORT_DIR'])
            if not target.is_absolute(): target = ROOT / target
            target.mkdir(parents=True, exist_ok=True)
            (target / (name + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return report

    def test_load_store_kernel(self):
        source = (Path(__file__).parent / 'examples/load_store.asm').read_text(encoding='utf-8')
        self.compare(source, 'load_store')

    def test_mixed_writeback_kernel(self):
        source = (Path(__file__).parent / 'examples/mixed_writeback.asm').read_text(encoding='utf-8')
        report = self.compare(source, 'mixed_writeback')
        self.assertGreater(report['writeback_collisions'], 0)

    def test_plasma_short(self):
        source = (ROOT / '22.fpga-gpu-bl8/examples/plasma_nommio.asm').read_text(encoding='utf-8')
        source, count = re.subn(r'MOVI\s+R6,\s*600', 'MOVI R6, 6', source)
        self.assertEqual(count, 1)
        self.compare(source, 'plasma_short')

    def test_mandelbrot_small(self):
        source = (ROOT / 'x.tests/cases-gpu/programs/mandelbrot/mandelbrot.asm').read_text(encoding='utf-8')
        for pattern, replacement in ((r'MOVI\s+R1,\s*320', 'MOVI R1, 16'),
                                     (r'MOVI\s+R2,\s*240', 'MOVI R2, 8'),
                                     (r'MOVHI\s+R3,\s*0x0001', 'MOVHI R3, 0'),
                                     (r'ORI\s+R3,\s*R3,\s*0x2C00', 'ORI R3, R3, 128'),
                                     (r'MOVI\s+R4,\s*256', 'MOVI R4, 16')):
            source, count = re.subn(pattern, replacement, source)
            self.assertEqual(count, 1)
        self.compare(source, 'mandelbrot_16x8')

    @unittest.skipUnless(os.environ.get('MINIGPU_FULL_PLASMA') == '1',
                         'full plasma frame: set MINIGPU_FULL_PLASMA=1')
    def test_plasma_full(self):
        source = (ROOT / '22.fpga-gpu-bl8/examples/plasma_nommio.asm').read_text(encoding='utf-8')
        report = self.compare(source, 'plasma_full')
        self.assertEqual(report['retired'], 151880)


if __name__ == '__main__': unittest.main()
