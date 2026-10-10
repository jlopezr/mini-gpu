"""`record_case.py` en GPU: que lanes y que ceros graba.

Por defecto graba la lane 0 y la ultima y omite los registros a cero. Eso deja
fuera justo lo que importa cuando un caso trata de QUE lane hace algo: una lane
intermedia que toma un salto, o un registro que debe seguir en cero porque la
lane murio antes de escribirlo.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from record_case import record  # noqa: E402

PROGRAM = """\
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BGE R1, R2, high
BRA join
high:
MOVI R3, 9
join:
HALT
"""


class RecordCaseGpuTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # El runner exige que el caso viva dentro del repo; `generated/` esta ignorada.
        base = ROOT / "generated"
        base.mkdir(exist_ok=True)
        cls.directory = Path(tempfile.mkdtemp(dir=base, prefix="record-case-"))
        (cls.directory / "program.asm").write_text(PROGRAM, encoding="utf-8")
        (cls.directory / "warps.json").write_text(json.dumps(
            {"warp_size": 8, "warps": [{"id": 0, "pc": 0, "active_mask": 255}]}), encoding="utf-8")
        cls.test_json = cls.directory / "test.json"
        cls.test_json.write_text(json.dumps({
            "architecture": "gpu", "name": "record-case-test", "program": "program.asm",
            "warp_config": "warps.json", "max_instructions": 1000, "expect": {}}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def lanes(self, **options):
        recorded = record(self.test_json, False, **options)
        return recorded["expect"]["warps"]["0"]["registers"]

    def test_por_defecto_solo_la_primera_y_la_ultima_y_sin_ceros(self):
        lanes = self.lanes()
        self.assertEqual(sorted(lanes), ["0", "7"])
        self.assertNotIn("R3", lanes["0"])
        self.assertEqual(lanes["7"]["R3"], 9)

    def test_all_lanes_vuelca_todas(self):
        self.assertEqual(sorted(self.lanes(all_lanes=True)), [str(n) for n in range(8)])

    def test_zeros_graba_el_cero_donde_otra_lane_vale_algo(self):
        lanes = self.lanes(all_lanes=True, zeros=True)
        self.assertEqual([lanes[str(n)]["R3"] for n in range(8)], [0, 0, 0, 0, 9, 9, 9, 9])

    def test_zeros_no_inventa_registros_que_nadie_usa(self):
        lanes = self.lanes(all_lanes=True, zeros=True)
        self.assertNotIn("R20", lanes["0"])
        # R1 es el tid: vale 0 en la lane 0 y 1..7 en las otras, asi que el 0 se graba.
        self.assertEqual(lanes["0"]["R1"], 0)

    def test_lo_grabado_sigue_pasando_en_el_runner(self):
        import run_tests as rt
        self.assertTrue(rt.load_case(self.test_json, "gpu")["name"])


if __name__ == "__main__":
    unittest.main()
