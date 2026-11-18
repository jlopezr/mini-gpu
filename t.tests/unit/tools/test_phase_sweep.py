"""phase_sweep: el prototipo sale de la ruta del bitstream, no de un numero escrito a mano."""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools import phase_sweep as ps  # noqa: E402


def repo(folder):
    """Un repo minimo: un prototipo con monitor.py y version.json, y una carpeta que no lo es."""
    root = Path(folder)
    proto = root / "38.fpga-cpu-pipelined"
    (proto / "reports" / "b1").mkdir(parents=True)
    (proto / "monitor.py").write_text("", encoding="utf-8")
    (root / "docs").mkdir()
    return root, proto


class PrototipoTest(unittest.TestCase):
    def test_sale_de_la_carpeta_del_bitstream(self):
        with tempfile.TemporaryDirectory() as folder:
            root, proto = repo(folder)
            bit = proto / "reports" / "b1" / "hardware.bit"
            self.assertEqual(ps.prototype_of(bit, root), proto)

    def test_fuera_de_un_prototipo_no_hay(self):
        with tempfile.TemporaryDirectory() as folder:
            root, _ = repo(folder)
            self.assertIsNone(ps.prototype_of(root / "docs" / "hardware.bit", root))
            self.assertIsNone(ps.prototype_of(root / "hardware.bit", root))
            self.assertIsNone(ps.prototype_of(Path("/tmp/otro/hardware.bit"), root))


class ArgumentosTest(unittest.TestCase):
    def test_bitstream_con_y_sin_nombre(self):
        with tempfile.TemporaryDirectory() as folder:
            _, proto = repo(folder)
            build = (proto / "reports" / "b1").resolve()
            self.assertEqual(ps.bitstream_arg(f"x={build}"), ps.Bitstream("x", build / "hardware.bit"))
            self.assertEqual(ps.bitstream_arg(str(build)).label, "b1")
            with self.assertRaises(argparse.ArgumentTypeError):
                ps.bitstream_arg(f"={build}")

    def test_fases(self):
        self.assertEqual(ps.phases_arg("0-2,10,47"), [0, 1, 2, 10, 47])
        with self.assertRaises(argparse.ArgumentTypeError):
            ps.phases_arg("40-48")

    def test_recomienda_el_centro_de_la_ventana_mas_larga_aunque_de_la_vuelta(self):
        self.assertEqual(ps.recommendation({46, 47, 0, 1, 2, 20}), 0)
        self.assertIsNone(ps.recommendation(set()))


if __name__ == "__main__":
    unittest.main()
