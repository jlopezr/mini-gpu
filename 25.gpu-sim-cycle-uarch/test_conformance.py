"""Reuse the repository's cases and runner; do not duplicate fixture parsing."""
import sys
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'x.tests'))
from backends.gpu_simulator import GpuBackend
from run_tests import load_case, compare_result


class ConformanceTests(unittest.TestCase):
    def test_existing_gpu_cases(self):
        self.run_cases(False)

    @unittest.skipUnless(os.environ.get('MINIGPU_FULL_CONFORMANCE') == '1',
                         'full-size Mandelbrot: set MINIGPU_FULL_CONFORMANCE=1')
    def test_full_size_mandelbrot(self):
        self.run_cases(True)

    def run_cases(self, programs):
        backend = GpuBackend(ROOT, 'cycle')
        for path in sorted((ROOT / 'x.tests/cases-gpu').rglob('test.json')):
            if ('programs' in path.parts) != programs: continue
            with self.subTest(case=str(path.relative_to(ROOT))):
                case = load_case(path)
                result = backend.run(
                    program=case['program'], initial_memory=case['initial_memory'],
                    register_numbers=set(), memory_ranges=list(case['expected']['memory']),
                    max_instructions=case['max_instructions'], timeout_seconds=60,
                    warp_config=case['warp_config'],
                    simulator_options=case.get('simulator_options'),
                )
                self.assertEqual(compare_result(case, result, 'gpu'), [])


if __name__ == '__main__': unittest.main()
