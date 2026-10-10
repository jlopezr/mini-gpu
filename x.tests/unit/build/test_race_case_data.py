"""Datos autocontenidos de los programas C de race."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools import race_case_data  # noqa: E402


class RaceCaseDataTest(unittest.TestCase):
    def test_blob_contains_the_comparator_block_and_its_single_input(self):
        for name in ("blur", "life", "rotate"):
            with self.subTest(name=name):
                spec = race_case_data.compare_race.WORKLOADS[name]
                case = spec.case(spec.default)
                blob = race_case_data.build_blob(name)
                self.assertEqual(
                    struct.unpack("<8I", blob[:32]),
                    (race_case_data.compare_race.WARPS, 8, *case.block),
                )
                self.assertEqual(blob[32:], case.memory[0][1])

    def test_cli_materializes_the_expected_dumps(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            output = folder / "case.bin"
            self.assertEqual(race_case_data.main([
                "blur", str(output), "--expected-dir", str(folder / "expected")
            ]), 0)
            case = race_case_data.build_case("blur")
            self.assertEqual(output.read_bytes(), race_case_data.build_blob("blur"))
            for index, (_address, data) in enumerate(case.expect):
                self.assertEqual(
                    (folder / "expected" / f"expected-{index}.bin").read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
