"""Un caso que se va a omitir por capacidades no debe construirse.

`load_case` ejecuta el `build` declarado por el caso antes de abrir sus artefactos. Si la
omisión por `requires` llegara después, se compilaría lo que no va a correr (y fallaría sin
`make` un caso que nunca se ejecutaría).
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_tests  # noqa: E402

MARCA = "construido"


def escribir_caso(directorio: Path, requires: list[str]) -> Path:
    (directorio / "p.bin").write_bytes(b"\x00\x00\x00\xfc")
    ruta = directorio / "test.json"
    ruta.write_text(json.dumps({
        "architecture": "cpu",
        "name": "caso-con-build",
        "program": "p.bin",
        "requires": requires,
        "expect": {"pc": "0x00000004"},
        "build": {"command": [sys.executable, "-c", f"open({MARCA!r}, 'w').close()"]},
    }), encoding="utf-8")
    return ruta


def ejecutar(directorio: Path) -> tuple[int, str, str]:
    salida, error = io.StringIO(), io.StringIO()
    argv = ["run_tests.py", "--backend", "sim-cpu", str(directorio)]
    with mock.patch.object(sys, "argv", argv), \
            contextlib.redirect_stdout(salida), contextlib.redirect_stderr(error):
        try:
            codigo = run_tests.main()
        except SystemExit as exc:
            codigo = exc.code
    return codigo, salida.getvalue(), error.getvalue()


class RazonAntesDelBuildTest(unittest.TestCase):
    VERSIONES = {"sim-cpu": "current"}

    def test_sin_capacidad_devuelve_la_razon_del_backend(self):
        razon = run_tests.skip_reason_before_build(
            {"name": "x", "requires": ["gpu_core"]}, "cpu", ["sim-cpu"], self.VERSIONES)
        self.assertIsNotNone(razon)
        self.assertTrue(razon.startswith("[sim-cpu]"))
        self.assertIn("gpu_core", razon)

    def test_con_las_capacidades_no_omite(self):
        self.assertIsNone(run_tests.skip_reason_before_build(
            {"name": "x", "requires": []}, "cpu", ["sim-cpu"], self.VERSIONES))


class BuildSoloSiCorreTest(unittest.TestCase):
    def test_un_caso_omitido_no_se_construye(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = Path(tmp)
            escribir_caso(directorio, ["gpu_core"])
            _, salida, _ = ejecutar(directorio)
            self.assertIn("SKIP caso-con-build", salida)
            self.assertNotIn("build:", salida)
            self.assertFalse((directorio / MARCA).exists())

    def test_un_caso_que_corre_si_se_construye(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = Path(tmp)
            escribir_caso(directorio, [])
            codigo, salida, error = ejecutar(directorio)
            self.assertEqual(codigo, 0, salida + error)
            self.assertIn("build:", salida)
            self.assertTrue((directorio / MARCA).exists())


if __name__ == "__main__":
    unittest.main()
