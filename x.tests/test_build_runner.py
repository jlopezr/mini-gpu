import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_runner import (  # noqa: E402
    BuildRunner,
    build_all,
    buildable_prototypes,
    clean_logs,
    create_build_record,
    list_builds,
    prototype_build_summary,
    process_exists,
    read_status,
    stop_build,
    tail_log,
    update_build_record,
)


class BuildRunnerTest(unittest.TestCase):
    def test_sweep_forwards_compare_and_apply_to_sweep_report(self):
        from tools import build_runner

        with tempfile.TemporaryDirectory() as temp:
            previous = Path(temp) / "sweep-x"
            with mock.patch("sys.argv", ["build_runner", "sweep", "-p", "17", "--seeds", "1", "2",
                                         "--compare", str(previous), "--apply", "--root", temp]), \
                 mock.patch.object(build_runner, "create_build_record",
                                   return_value={"folder": Path(temp), "status_path": Path(temp) / "s"}), \
                 mock.patch.object(build_runner, "_run_and_track", return_value=0) as run:
                self.assertEqual(build_runner._main(), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--compare") + 1], str(previous.resolve()))
            self.assertIn("--apply", command)

    def test_sweep_list_and_show_query_without_creating_a_build_record(self):
        from tools import build_runner

        for flags, expected in ((["--list"], ["--list"]), (["--show", "latest"], ["--show", "latest"])):
            with mock.patch("sys.argv", ["build_runner", "sweep", "-p", "6", *flags]), \
                 mock.patch.object(build_runner, "create_build_record") as record, \
                 mock.patch.object(build_runner.subprocess, "run",
                                   return_value=mock.Mock(returncode=0)) as run:
                self.assertEqual(build_runner._main(), 0)
            record.assert_not_called()
            self.assertEqual(run.call_args.args[0][-len(expected):], expected)

    def test_process_exists_recognizes_current_and_missing_pid(self):
        self.assertTrue(process_exists(os.getpid()))
        self.assertFalse(process_exists(2 ** 30))

    def test_prototype_summary_does_not_change_a_live_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prototype = root / "1.live"
            prototype.mkdir()
            (prototype / "apio.ini").write_text("[apio]\n", encoding="utf-8")
            reports = root / "reports"
            record = create_build_record(reports, prototype.name, "build", ["build"])
            update_build_record(record["status_path"], pid=os.getpid())

            rows = prototype_build_summary(root, reports)

            self.assertEqual(rows[0]["state"], "RUNNING")
            self.assertEqual(rows[0]["bitstream"], "MISSING")
            self.assertEqual(read_status(record["status_path"])["state"], "running")

    def test_a_failed_test_run_does_not_hide_the_last_build(self):
        # TODO 15: `test --lint-only` acababa FAILED y pasaba a ser "el ultimo
        # build" de la tabla, en rojo, con la sintesis bien.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prototype = root / "1.lint"
            prototype.mkdir()
            (prototype / "apio.ini").write_text("[apio]\n", encoding="utf-8")
            reports = root / "reports"
            build = create_build_record(reports, prototype.name, "build", ["build"])
            update_build_record(build["status_path"], state="success", exit_code=0,
                                started_at="2026-10-01T10:00:00Z")
            lint = create_build_record(reports, prototype.name, "test", ["test", "--lint-only"])
            update_build_record(lint["status_path"], state="failed", exit_code=1,
                                started_at="2026-10-01T11:00:00Z")

            rows = prototype_build_summary(root, reports)

            self.assertEqual(rows[0]["state"], "SUCCESS")
            self.assertEqual(rows[0]["label"], "build")

    def test_every_clock_is_listed_when_there_is_more_than_one(self):
        import io
        from contextlib import redirect_stdout
        from tools.build_runner import _clock_details, print_prototype_build_summary

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            (archive / "summary.json").write_text(json.dumps({"clocks": {
                "$glbnet$clk": {"achieved": 83.2, "constraint": 80},
                "$glbnet$sdram_clk$TRELLIS_IO_OUT": {"achieved": 85.5, "constraint": 100},
                "$glbnet$clk_25mhz$TRELLIS_IO_IN": {"achieved": 37.8, "constraint": 25},
            }}), encoding="utf-8")
            clocks = _clock_details(archive)

        # Primero el que menos margen tiene, con el nombre sin prefijo ni sufijo.
        self.assertEqual([name for name, _, _ in clocks], ["sdram_clk", "clk", "clk_25mhz"])
        self.assertEqual(_clock_details(None), [])

        row = {"prototype": "9.multi", "bitstream": "CURRENT", "state": "SUCCESS",
               "timing": "FAIL", "fmax": "85.5/100.0", "seed": "7", "elapsed": "01:00",
               "date": "-", "label": "build", "clocks": clocks}
        single = dict(row, prototype="8.single", clocks=clocks[:1])
        out = io.StringIO()
        with redirect_stdout(out):
            print_prototype_build_summary([row, single])
        lines = out.getvalue().splitlines()
        # La cabecera, el prototipo con tres relojes y su linea extra, y el de uno.
        self.assertEqual(len(lines), 4)
        self.assertIn("sdram_clk 85.5/100!", lines[2])
        self.assertIn("clk 83.2/80", lines[2])
        self.assertNotIn("clk 83.2/80!", lines[2])
        self.assertIn("8.single", lines[3])

    def test_a_running_test_is_still_shown_as_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prototype = root / "1.live"
            prototype.mkdir()
            (prototype / "apio.ini").write_text("[apio]\n", encoding="utf-8")
            reports = root / "reports"
            record = create_build_record(reports, prototype.name, "test", ["test"])
            update_build_record(record["status_path"], pid=os.getpid())

            rows = prototype_build_summary(root, reports)

            self.assertEqual(rows[0]["state"], "RUNNING")

    def test_build_all_runs_apio_prototypes_sequentially_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("2.second", "1.first", "3.no-apio"):
                (root / name).mkdir()
            (root / "1.first" / "apio.ini").write_text("[apio]\n", encoding="utf-8")
            (root / "2.second" / "apio.ini").write_text("[apio]\n", encoding="utf-8")
            run = mock.Mock(side_effect=[SimpleNamespace(returncode=2), SimpleNamespace(returncode=0)])

            result = build_all(root, run=run)

            self.assertEqual(result, 1)
            self.assertEqual([call.args[0][5] for call in run.call_args_list],
                             ["1.first", "2.second"])
            self.assertEqual(buildable_prototypes(root), [root / "1.first", root / "2.second"])
    def test_status_json_is_created_and_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = create_build_record(root, "17.fpga-gpu-ram-v2", "synth", ["python", "-c", "print('hi')"])
            self.assertTrue(record["status_path"].exists())
            self.assertEqual(read_status(record["status_path"])["state"], "running")
            update_build_record(record["status_path"], state="success", exit_code=0)
            self.assertEqual(read_status(record["status_path"])["state"], "success")

    def test_tail_log_returns_last_n_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "build.log"
            log_path.write_text("a\n" * 5, encoding="utf-8")
            self.assertEqual(len(tail_log(log_path, 2).splitlines()), 2)

    def test_follow_log_reads_new_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "build.log"
            log_path.write_text("first\n", encoding="utf-8")
            result = {}

            def worker():
                time.sleep(0.2)
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write("second\n")
                    handle.flush()
                result["done"] = True

            thread = threading.Thread(target=worker)
            thread.start()
            lines = []
            for line in BuildRunner.follow_log(log_path, timeout=1.0):
                lines.append(line)
                if "second" in line:
                    break
            thread.join()
            self.assertIn("second", "\n".join(lines))

    def test_stop_build_terminates_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "loop.py"
            script.write_text("import time\nwhile True:\n    time.sleep(0.1)\n", encoding="utf-8")
            proc = subprocess.Popen(["python", str(script)])
            status = create_build_record(root, "17.fpga-gpu-ram-v2", "loop", ["python", str(script)])
            status_path = status["status_path"]
            read_status(status_path)["pid"] = proc.pid
            with status_path.open("w", encoding="utf-8") as handle:
                json.dump({"pid": proc.pid, "state": "running", "command": ["python", str(script)]}, handle)
            self.assertTrue(stop_build(status_path))
            time.sleep(0.2)
            self.assertNotEqual(proc.poll(), None)

    def test_list_builds_returns_recent_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record1 = create_build_record(root, "17.fpga-gpu-ram-v2", "one", ["echo", "one"])
            record2 = create_build_record(root, "17.fpga-gpu-ram-v2", "two", ["echo", "two"])
            update_build_record(record1["status_path"], state="success")
            update_build_record(record2["status_path"], state="failed")
            entries = list_builds(root)
            self.assertEqual(len(entries), 2)
            self.assertIn("one", "\n".join(entry["label"] for entry in entries))

    def test_list_builds_marks_dead_running_process_as_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = create_build_record(root, "17.fpga-gpu-ram-v2", "orphan", ["echo", "old"])
            update_build_record(record["status_path"], pid=2 ** 30)

            entry = list_builds(root)[0]

            self.assertEqual(entry["state"], "interrupted")
            self.assertIsNotNone(entry["finished_at"])
            self.assertEqual(read_status(record["status_path"])["state"], "interrupted")

    def test_list_builds_keeps_live_running_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = create_build_record(root, "17.fpga-gpu-ram-v2", "active", ["echo", "new"])
            update_build_record(record["status_path"], pid=os.getpid())

            entry = list_builds(root)[0]

            self.assertEqual(entry["state"], "running")

    def test_clean_logs_dry_run_keeps_active_and_last_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = create_build_record(root, "17.fpga-gpu-ram-v2", "active", ["sleep", "10"])
            stale = create_build_record(root, "17.fpga-gpu-ram-v2", "stale", ["echo", "old"])
            success = create_build_record(root, "17.fpga-gpu-ram-v2", "last-good", ["echo", "good"])
            update_build_record(active["status_path"], state="running", pid=os.getpid())
            update_build_record(stale["status_path"], state="failed")
            update_build_record(success["status_path"], state="success")
            summary = clean_logs(root, keep=1, dry_run=True, yes=False)
            self.assertIn(str(stale["folder"]), summary["would_remove"])
            self.assertTrue(active["folder"].exists())
            self.assertTrue(success["folder"].exists())
            self.assertGreater(summary["bytes_freed"], 0)


if __name__ == "__main__":
    unittest.main()
