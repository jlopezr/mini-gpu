"""`tools/run-tests`: qué opciones son suyas y qué se reenvía a `run_tests.py`."""

import sys
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cargar():
    ruta = str(ROOT / "tools" / "run-tests")
    spec = spec_from_loader("run_tests_launcher", SourceFileLoader("run_tests_launcher", ruta))
    modulo = module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


lanzador = cargar()


class ParsearTest(unittest.TestCase):
    def test_sin_argumentos(self):
        args, extra = lanzador.parsear([])
        self.assertFalse(args.quick or args.verbose or args.hardware)
        self.assertEqual(extra, [])

    def test_las_opciones_propias_se_consumen(self):
        args, extra = lanzador.parsear(["--quick", "--verbose", "--hardware"])
        self.assertTrue(args.quick and args.verbose and args.hardware)
        self.assertEqual(extra, [])

    def test_lo_desconocido_se_reenvia_en_orden_con_sus_valores(self):
        _, extra = lanzador.parsear(["--backend", "sim-cpu", "-p", "21", "cases-cpu/x/test.json"])
        self.assertEqual(extra, ["--backend", "sim-cpu", "-p", "21", "cases-cpu/x/test.json"])

    def test_mezcla_de_propias_y_reenviadas(self):
        args, extra = lanzador.parsear(["--trace", "--quick", "--backend", "sim-gpu"])
        self.assertTrue(args.quick)
        self.assertEqual(extra, ["--trace", "--backend", "sim-gpu"])

    def test_despues_de_dos_guiones_no_se_interpreta_nada(self):
        args, extra = lanzador.parsear(["--quick", "--", "--verbose", "--quick"])
        self.assertTrue(args.quick)
        self.assertFalse(args.verbose)
        self.assertEqual(extra, ["--verbose", "--quick"])

    def test_no_se_abrevia(self):
        """`--ver` no puede convertirse en `--verbose`: es de `run_tests.py`."""
        args, extra = lanzador.parsear(["--ver"])
        self.assertFalse(args.verbose)
        self.assertEqual(extra, ["--ver"])


if __name__ == "__main__":
    unittest.main()
