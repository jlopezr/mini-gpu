"""El backend `sim-sys`: el simulador CPU+GPU de la 32 dentro de `run_tests.py`.

Es un backend de CPU --el caso lo escribe y lo observa la CPU-- que declara
`gpu_core` y `gpu_warp_start`, así que `cases-cpu/gpu/*` corre también sin placa.
Lo que hay que fijar es que sigue siendo un `sim-cpu` para todo lo demás y que
no se confunde con `fpga-sys`, que es de GPU.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_tests  # noqa: E402
from backends import cpu_gpu_simulator, simulator  # noqa: E402

CASOS_GPU = ROOT / "cases-cpu" / "gpu"


class DefinicionTest(unittest.TestCase):
    def test_es_un_simulador_de_cpu(self):
        definicion = run_tests.BACKEND_DEFINITIONS["sim-sys"]
        self.assertEqual(definicion["architecture"], "cpu")
        self.assertIn("sim-sys", run_tests.SIMULADORES)
        self.assertNotIn("sim-sys", run_tests.SIMULADORES_GPU)

    def test_tiene_las_capacidades_de_sim_cpu_y_las_de_gpu_core(self):
        propias = cpu_gpu_simulator.capabilities()
        self.assertLessEqual(simulator.capabilities(), propias)
        self.assertLessEqual({"gpu_core", "gpu_warp_start"}, propias)
        self.assertNotIn("gpu_core", simulator.capabilities())

    def test_su_pareja_en_placa_es_fpga_cpu_y_no_fpga_sys(self):
        self.assertEqual(run_tests.BACKEND_DEFINITIONS["fpga-sys"]["architecture"], "gpu")
        self.assertNotIn("sim-sys", run_tests.BACKENDS_DE_PLACA)


class IncompatibilidadTest(unittest.TestCase):
    def test_un_caso_de_gpu_core_solo_cabe_en_sim_sys(self):
        caso = {"requires": ["gpu_core"]}
        self.assertIsNone(cpu_gpu_simulator.incompatibility(caso))
        self.assertIn("gpu_core", simulator.incompatibility(caso))


class EjecucionTest(unittest.TestCase):
    """Los dos casos reales de `cases-cpu/gpu` contra el simulador."""

    @classmethod
    def setUpClass(cls):
        cls.backend = cpu_gpu_simulator.CpuGpuSimulatorBackend(ROOT.parent)

    def ejecutar(self, nombre):
        args = type("Args", (), dict(trace=False, trace_detail=False,
                                     trace_limit=None, trace_file=None))()
        caso = run_tests.load_case(CASOS_GPU / nombre / "test.json", "cpu")
        resultado = self.backend.run(**run_tests.backend_arguments(
            caso, "sim-sys", args))
        return caso, resultado

    def test_launch_run_deja_los_registros_esperados(self):
        caso, resultado = self.ejecutar("launch-run")
        self.assertTrue(resultado["halted"])
        self.assertFalse(resultado["error"])
        for numero, valor in caso["expected"]["registers"].items():
            self.assertEqual(resultado["registers"][numero], valor)

    def test_launch_start_termina_sin_error(self):
        _, resultado = self.ejecutar("launch-start")
        self.assertTrue(resultado["halted"])
        self.assertFalse(resultado["error"])


if __name__ == "__main__":
    unittest.main()
