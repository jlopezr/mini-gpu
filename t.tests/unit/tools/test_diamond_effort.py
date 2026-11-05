"""diamond_effort: columna SEED de Diamond (cost table de la iteracion guardada)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.build_runner import diamond_effort  # noqa: E402


def effort(summary):
    with tempfile.TemporaryDirectory() as folder:
        if summary is not None:
            (Path(folder) / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return diamond_effort(Path(folder))


class DiamondEffortTests(unittest.TestCase):
    def test_first_attempt_means_no_search(self):
        self.assertEqual(effort({"saved_iteration": "5_1"}), "-")

    def test_search_shows_the_saved_cost_table(self):
        self.assertEqual(effort({"saved_iteration": "5_8"}), "8")

    def test_missing_or_failed_report_is_a_dash(self):
        self.assertEqual(effort({"saved_iteration": None}), "-")
        self.assertEqual(effort(None), "-")


if __name__ == "__main__":
    unittest.main()
