"""`tools/test_all.py`: el analisis de la salida del runner y la matriz, sin placa."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools import test_all  # noqa: E402

SALIDA = """\
Puerto detectado: COM3 (USB Serial Port (COM3))
SKIP demo-plasma [gpu-fpga]: sin frame_capture
SKIP ssy-region-overflow [gpu-fpga]: las profundidades SIMT del caso requieren el simulador
SKIP gpu-mandelbrot: dump esperado fuera del mapa de memoria: 0x100000
PASS demo-smoke [gpu-fpga] (0.3s)
FAIL gpu-vecsum [gpu-fpga]
  warp 0 pc: esperado 32, obtenido 28
  memoria 0x180: distinta
PASS gpu-vecsum-partial [gpu-fpga]
4 caso(s), 1 fallo(s), 3 omitido(s) por arquitectura o capacidades, 2.0s
"""


class ParseTest(unittest.TestCase):

    def setUp(self):
        self.results, self.summary = test_all.parse_output(SALIDA)

    def test_distingue_pass_fail_y_skip(self):
        states = {name: state for name, (state, _d) in self.results.items()}
        self.assertEqual(states, {
            "demo-plasma": "SKIP", "ssy-region-overflow": "SKIP", "gpu-mandelbrot": "SKIP",
            "demo-smoke": "PASS", "gpu-vecsum": "FAIL", "gpu-vecsum-partial": "PASS"})

    def test_el_skip_conserva_su_motivo_con_y_sin_backend_entre_corchetes(self):
        self.assertEqual(self.results["demo-plasma"][1], "sin frame_capture")
        self.assertIn("fuera del mapa", self.results["gpu-mandelbrot"][1])

    def test_el_fallo_recoge_las_lineas_de_detalle(self):
        detail = self.results["gpu-vecsum"][1]
        self.assertIn("esperado 32, obtenido 28", detail)
        self.assertIn("memoria 0x180", detail)
        # y no arrastra el detalle al caso siguiente
        self.assertEqual(self.results["gpu-vecsum-partial"][1], "")

    def test_lee_el_resumen_final(self):
        self.assertEqual(self.summary.groups(), ("4", "1", "3"))


class MatrixTest(unittest.TestCase):

    def test_un_caso_que_un_prototipo_no_tiene_sale_con_guion(self):
        a = {"x": ("PASS", ""), "solo-a": ("PASS", "")}
        b = {"x": ("SKIP", "sin video")}
        table = test_all.matrix([("12", a, None), ("22", b, None)])
        row = [l for l in table.splitlines() if l.startswith("| solo-a")][0]
        self.assertEqual(row, "| solo-a | PASS | — |")

    def test_un_prototipo_con_error_de_arranque_marca_toda_su_columna(self):
        table = test_all.matrix([("12", {"x": ("PASS", "")}, None), ("22", {}, "ERROR")])
        self.assertIn("| x | PASS | ERROR |", table)

    def test_el_informe_lista_los_fallos_y_el_porque_de_los_omitidos(self):
        results, _ = test_all.parse_output(SALIDA)
        report = test_all.build_report("gpu", [("22", results, None)], [None])
        self.assertIn("## Fallos", report)
        self.assertIn("**22** `gpu-vecsum`", report)
        self.assertIn("`demo-plasma` (22): sin frame_capture", report)


class PasadaIncompletaTest(unittest.TestCase):
    """Una pasada que muere a mitad no puede salir como «OK»."""

    def _informe(self, salida: str, codigo: int) -> tuple[str, int]:
        import tempfile
        from unittest import mock

        resultados, resumen = test_all.parse_output(salida)
        pasada = (resultados, resumen, salida, codigo)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(test_all, "run_prototype", return_value=pasada), \
                mock.patch.object(test_all, "prototypes",
                                  return_value=[("cpu", 16, "16.fpga-cpu-hdmi")]):
            destino = Path(tmp) / "informe.md"
            devuelto = test_all.main(["--family", "cpu", "-o", str(destino)])
            return destino.read_text(encoding="utf-8"), devuelto

    def test_codigo_distinto_de_cero_sin_fail_es_incompleto(self):
        # Solo SKIP y luego una excepcion del arnes: ni un PASS ni un FAIL.
        salida = ("SKIP calls-jump-table [cpu-fpga]: sin calls\n"
                  "ERROR x/test.json: [Errno 5] puerto desaparecido\n")
        informe, codigo = self._informe(salida, 2)
        self.assertEqual(codigo, 1)
        self.assertIn("INCOMPLETO (codigo 2)", informe)
        self.assertNotIn("| OK |", informe)

    def test_una_pasada_limpia_sigue_siendo_ok(self):
        salida = ("PASS smoke [cpu-fpga]\n"
                  "1 caso(s), 0 fallo(s), 0 omitido(s) por arquitectura o capacidades, 1s\n")
        informe, codigo = self._informe(salida, 0)
        self.assertEqual(codigo, 0)
        self.assertIn("| OK |", informe)

    def test_los_resultados_parciales_se_conservan_en_la_matriz(self):
        salida = ("PASS smoke [cpu-fpga]\n"
                  "ERROR x/test.json: se cayo\n")
        informe, _ = self._informe(salida, 2)
        self.assertIn("| smoke | PASS |", informe)


if __name__ == "__main__":
    unittest.main()
