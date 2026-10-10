"""`build-c --load`: compila para la placa y delega la carga en `run_board.main_load`.

Sin compilador ni placa: `build` y `main_load` se sustituyen por dobles. Lo que se
fija es qué se le pide a cada uno.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))

import build_c  # noqa: E402
import run_board  # noqa: E402


class LoadTest(unittest.TestCase):
    def run_main(self, *args):
        image = mock.Mock(spec=Path)
        image.stat.return_value.st_size = 4
        image.__str__ = lambda self: "img.bin"
        with mock.patch.object(build_c, "build", return_value=image) as build, \
                mock.patch.object(run_board, "main_load", return_value=0) as load:
            code = build_c.main(["prog.c", *args])
        return code, build, load

    def test_sin_load_no_toca_la_placa(self):
        code, build, load = self.run_main()
        self.assertEqual(code, 0)
        self.assertFalse(build.call_args.args[2])        # board
        load.assert_not_called()

    def test_load_compila_para_placa_y_carga_en_la_36(self):
        _, build, load = self.run_main("--load")
        self.assertTrue(build.call_args.args[2])
        load.assert_called_once_with(["-p", "36", "--program", "img.bin"])

    def test_load_acepta_otro_prototipo_y_no_run(self):
        _, _, load = self.run_main("--load", "37", "--no-run")
        load.assert_called_once_with(["-p", "37", "--program", "img.bin", "--no-run"])


if __name__ == "__main__":
    unittest.main()
