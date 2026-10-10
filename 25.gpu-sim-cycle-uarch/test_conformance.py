"""Reuse the repository's cases and runner; do not duplicate fixture parsing."""
import sys
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'x.tests'))
from backends.sim_gpu import SimGpuBackend, incompatibility
from run_tests import backend_arguments, load_case, compare_result


class ConformanceTests(unittest.TestCase):
    def test_existing_gpu_cases(self):
        self.run_cases(False)

    @unittest.skipUnless(os.environ.get('MINIGPU_FULL_CONFORMANCE') == '1',
                         'full-size Mandelbrot: set MINIGPU_FULL_CONFORMANCE=1')
    def test_full_size_mandelbrot(self):
        self.run_cases(True)

    def run_cases(self, programs):
        backend = SimGpuBackend(ROOT, 'cycle')
        # La conformidad debe preparar cada caso igual que el runner público.
        # En particular, backend_arguments conecta vídeo/serie y transmite las
        # opciones del modelo; construir esta lista a mano fue lo que dejó
        # Plasma sin VideoDevice cuando el contrato del runner creció.
        args = SimpleNamespace(
            trace=False,
            trace_detail=False,
            trace_limit=None,
            trace_file=None,
        )
        for path in sorted((ROOT / 'x.tests/cases-gpu').rglob('test.json')):
            if ('programs' in path.parts) != programs: continue
            with self.subTest(case=str(path.relative_to(ROOT))):
                case = load_case(path)
                # Es un SKIP de compatibilidad, no un fallo del programa. Por
                # ejemplo, mmio-selftest exige contadores que el modelo ciclo
                # declara honestamente que no implementa.
                if incompatibility(case, 'cycle') is not None:
                    continue
                result = backend.run(**backend_arguments(case, 'sim-gpu-cycle', args))
                self.assertEqual(compare_result(case, result, 'gpu'), [])


if __name__ == '__main__': unittest.main()
