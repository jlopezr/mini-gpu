"""`input_vectors.hex` es salida del oraculo, no un fichero a mano.

`30.fpga-cpu-console/input_registers_tb.v` compara el RTL de INPUT contra este
fichero. Si el oraculo (`InputDevice`) cambia y el fichero no se regenera, el
banco pasaria o fallaria contra una version vieja del contrato.

Regenerar con `python -m tools.gen_input_vectors`.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools import gen_input_vectors


class InputVectorsTest(unittest.TestCase):
    def test_el_fichero_versionado_coincide_con_el_oraculo(self):
        versionado = gen_input_vectors.OUTPUT.read_text(encoding="ascii")
        self.assertEqual(
            versionado.replace("\r\n", "\n"),
            gen_input_vectors.render(gen_input_vectors.build_vectors()),
            "input_vectors.hex esta desfasado: python -m tools.gen_input_vectors")

    def test_cubre_todas_las_operaciones(self):
        usadas = {op for op, _, _ in gen_input_vectors.build_vectors()}
        self.assertEqual(usadas, set(range(11)))


if __name__ == "__main__":
    unittest.main()
