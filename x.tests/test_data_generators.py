"""`load_data_file` ejecuta el generador del caso cuando falta el fichero.

Los `*.bin` están ignorados por git (x.tests/.gitignore), así que en un clon
limpio faltan los esperados que se calculan con `reference.py` o
`make_expected.py`. El runner los genera al vuelo, y solo cuando faltan.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from run_tests import load_data_file

ESCRIBE_FRAME = """\
from pathlib import Path
destino = Path(__file__).parent / "expected" / "frame.bin"
destino.parent.mkdir(exist_ok=True)
destino.write_bytes(b"\\x01\\x02\\x03\\x04")
"""


class DataGeneratorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.caso = Path(self._tmp.name)
        self.esperado = self.caso / "expected" / "frame.bin"

    def cargar(self, ruta):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_data_file(ruta)

    def test_missing_file_is_generated_by_reference_py(self):
        (self.caso / "reference.py").write_text(ESCRIBE_FRAME, encoding="utf-8")
        self.assertEqual(self.cargar(self.esperado), b"\x01\x02\x03\x04")

    def test_make_expected_py_is_also_a_generator(self):
        (self.caso / "make_expected.py").write_text(ESCRIBE_FRAME, encoding="utf-8")
        self.assertEqual(self.cargar(self.esperado), b"\x01\x02\x03\x04")

    def test_existing_file_is_not_regenerated(self):
        self.esperado.parent.mkdir()
        self.esperado.write_bytes(b"grabado")
        (self.caso / "reference.py").write_text(ESCRIBE_FRAME, encoding="utf-8")
        self.assertEqual(self.cargar(self.esperado), b"grabado")
        self.assertEqual(self.esperado.read_bytes(), b"grabado")

    def test_missing_file_without_generator_keeps_the_usual_error(self):
        with self.assertRaises(FileNotFoundError):
            self.cargar(self.esperado)

    def test_generator_that_leaves_no_file_keeps_the_usual_error(self):
        (self.caso / "reference.py").write_text("pass\n", encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            self.cargar(self.esperado)

    def test_failing_generator_reports_its_output(self):
        (self.caso / "reference.py").write_text(
            "import sys\nsys.exit('sin modelo')\n", encoding="utf-8")
        with self.assertRaises(ValueError) as error:
            self.cargar(self.esperado)
        self.assertIn("reference.py", str(error.exception))
        self.assertIn("sin modelo", str(error.exception))

    def test_file_next_to_the_generator_is_found_too(self):
        # `warp-lane-bands` deja `expected.bin` junto a `reference.py`, sin
        # carpeta `expected/`.
        (self.caso / "reference.py").write_text(
            "from pathlib import Path\n"
            "Path(__file__).with_name('expected.bin').write_bytes(b'abcd')\n",
            encoding="utf-8")
        self.assertEqual(self.cargar(self.caso / "expected.bin"), b"abcd")


if __name__ == "__main__":
    unittest.main()
