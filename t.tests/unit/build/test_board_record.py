import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import board_record  # noqa: E402


def result(status="pass"):
    return {"case": "c", "backend": "fpga-cpu", "path": "p", "status": status,
            "errors": [], "seconds": 0.1, "case_sha256": "x"}


class BoardRecordTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state" / "board-state.json"
        patcher = patch.object(board_record, "STATE_FILE", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.project = self.root / "36.proto"
        (self.project / "reports" / "build-a").mkdir(parents=True)
        (self.project / "cpu.v").write_text("module cpu; endmodule", encoding="utf-8")
        (self.project / "reports" / "build-a" / "hardware.bit").write_bytes(b"bitstream-A")
        (self.project / "reports" / "build-b").mkdir()
        (self.project / "reports" / "build-b" / "hardware.bit").write_bytes(b"bitstream-B")

    def record(self, results):
        return board_record.build_record(
            project=self.project, root=self.root, port="COM3", family=["cpu"],
            arguments=[], full_suite=True, results=results, skipped=3,
            monitor_before=(5, 36), monitor_after=(5, 36))

    def test_folder_hash_changes_with_content_and_name(self):
        case = self.root / "case"
        case.mkdir()
        (case / "test.json").write_text("{}", encoding="utf-8")
        first = board_record.folder_sha256(case)
        board_record._folder_cache.clear()
        (case / "program.asm").write_text("HALT", encoding="utf-8")
        self.assertNotEqual(first, board_record.folder_sha256(case))

    def _build(self, name, tool=None, exit_code=0, bit=True):
        folder = self.project / "reports" / name
        folder.mkdir(parents=True, exist_ok=True)
        metadata = {"exit_code": exit_code}
        if tool:
            metadata["tool"] = tool
        (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        if bit:
            (folder / "hardware.bit").write_bytes(name.encode())
        return folder

    def test_latest_build_is_per_toolchain_and_newest_first(self):
        old = self._build("20261001-d1-diamond", "diamond")
        new = self._build("20261002-d2-diamond", "diamond")
        apio = self._build("20261003-a1-build")
        with patch.object(board_record, "sources_match", return_value=True):
            self.assertEqual(board_record.find_latest_build(self.project, "diamond")[0], new)
            self.assertEqual(board_record.find_latest_build(self.project, "apio")[0], apio)
        self.assertNotEqual(old, new)

    def test_latest_build_skips_failed_builds_and_stale_sources(self):
        good = self._build("20261001-ok-diamond", "diamond")
        self._build("20261002-failed-diamond", "diamond", exit_code=1)
        self._build("20261003-nobit-diamond", "diamond", bit=False)
        stale = self._build("20261004-stale-diamond", "diamond")
        with patch.object(board_record, "sources_match",
                          side_effect=lambda project, folder: folder != stale):
            self.assertEqual(board_record.find_latest_build(self.project, "diamond")[0], good)

    def test_latest_build_explains_why_there_is_none(self):
        self._build("20261001-a-diamond", "diamond")
        with patch.object(board_record, "sources_match", return_value=False):
            folder, reason = board_record.find_latest_build(self.project, "diamond")
        self.assertIsNone(folder)
        self.assertIn("ninguno con las fuentes actuales", reason)
        folder, reason = board_record.find_latest_build(self.project, "apio")
        self.assertIsNone(folder)
        self.assertIn("ningun build de apio", reason)

    def test_record_is_attached_to_the_build_with_that_bitstream(self):
        board_record.record_upload(self.project, self.project / "reports" / "build-b" / "hardware.bit")
        record = self.record([result(), result("fail")])
        self.assertEqual(record["bitstream"]["build_folder"], "build-b")
        self.assertEqual(record["totals"]["pass"], 1)
        self.assertEqual(record["totals"]["fail"], 1)
        path = board_record.write_record(self.project, record)
        self.assertEqual(path, self.project / "reports" / "build-b" / "board-tests.json")
        self.assertEqual(board_record.board_status(self.project / "reports" / "build-b"),
                         f"1/2 {record['timestamp'][:10]}")
        self.assertEqual(board_record.board_status(self.project / "reports" / "build-a"), "UNTESTED")

    def test_prototype_without_cpu_or_gpu_is_not_applicable(self):
        (self.project / "cpu.v").unlink()
        self.assertEqual(board_record.board_status(self.project / "reports" / "build-a"), "-")

    def test_runs_accumulate_in_the_same_file(self):
        board_record.record_upload(self.project, self.project / "reports" / "build-a" / "hardware.bit")
        for _ in range(2):
            board_record.write_record(self.project, self.record([result()]))
        data = json.loads((self.project / "reports" / "build-a" / "board-tests.json").read_text())
        self.assertEqual(len(data["runs"]), 2)

    def test_unknown_bitstream_goes_to_its_own_folder_and_says_so(self):
        # La placa se programo desde otro sitio: el bitstream no esta en ningun build.
        outside = self.root / "outside.bit"
        outside.write_bytes(b"something else")
        board_record.record_upload(self.project, outside)
        record = self.record([result()])
        self.assertIsNone(record["bitstream"]["build_folder"])
        path = board_record.write_record(self.project, record)
        self.assertIn("board-tests-sin-build", str(path))

    def test_no_recorded_upload_is_reported_as_unknown(self):
        record = self.record([result()])
        self.assertIsNone(record["bitstream"]["sha256"])
        self.assertIn("desconocida", record["bitstream"]["provenance"])

    def test_upload_of_another_prototype_is_flagged(self):
        other = self.root / "37.other"
        other.mkdir()
        bit = other / "hardware.bit"
        bit.write_bytes(b"x")
        board_record.record_upload(other, bit)
        self.assertIn("otro prototipo", self.record([result()])["bitstream"]["provenance"])

    def test_cases_that_never_reached_the_board_count_against_the_total(self):
        board_record.record_upload(self.project, self.project / "reports" / "build-a" / "hardware.bit")
        record = board_record.build_record(
            project=self.project, root=self.root, port="COM3", family=["cpu"],
            arguments=[], full_suite=True, results=[result(), result()], skipped=0,
            unprepared=3, monitor_before=None, monitor_after=None)
        board_record.write_record(self.project, record)
        self.assertTrue(board_record.board_status(
            self.project / "reports" / "build-a").startswith("2/5 "))
        self.assertIn("3 sin preparar", board_record.summary_line(record))

    def test_sources_match_ignores_line_endings_and_detects_real_changes(self):
        (self.project / "top.v").write_bytes(b"module top;\r\nendmodule\n")   # mezcla CRLF/LF
        build = self.project / "reports" / "build-a"
        lf = board_record.normalized_source_hashes(self.project)
        (build / "metadata.json").write_text(json.dumps({"source_sha256_lf": lf}), encoding="utf-8")
        self.assertTrue(board_record.sources_match(self.project, build))
        (self.project / "top.v").write_bytes(b"module top;\r\nendmodule\r\n")  # solo saltos de linea
        self.assertTrue(board_record.sources_match(self.project, build))
        (self.project / "top.v").write_bytes(b"module top2;\nendmodule\n")     # RTL distinto
        self.assertFalse(board_record.sources_match(self.project, build))

    def test_legacy_build_with_different_bytes_is_not_verifiable_instead_of_false_alarm(self):
        (self.project / "top.v").write_bytes(b"module top;\r\nendmodule\r\n")
        build = self.project / "reports" / "build-a"
        (build / "metadata.json").write_text(
            json.dumps({"source_sha256": {"top.v": "0" * 64}}), encoding="utf-8")
        self.assertIsNone(board_record.sources_match(self.project, build))

    def test_partial_runs_are_marked_in_the_status(self):
        board_record.record_upload(self.project, self.project / "reports" / "build-a" / "hardware.bit")
        record = board_record.build_record(
            project=self.project, root=self.root, port="COM3", family=["cpu"],
            arguments=["x/test.json"], full_suite=False, results=[result()], skipped=0,
            monitor_before=None, monitor_after=None)
        board_record.write_record(self.project, record)
        self.assertIn("parcial", board_record.board_status(self.project / "reports" / "build-a"))


if __name__ == "__main__":
    unittest.main()
