import json
import os
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tools.build_runner import (
    BuildRunner,
    clean_logs,
    create_build_record,
    list_builds,
    read_status,
    stop_build,
    tail_log,
    update_build_record,
)


class BuildRunnerTest(unittest.TestCase):
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

    def test_clean_logs_dry_run_keeps_active_and_last_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = create_build_record(root, "17.fpga-gpu-ram-v2", "active", ["sleep", "10"])
            stale = create_build_record(root, "17.fpga-gpu-ram-v2", "stale", ["echo", "old"])
            success = create_build_record(root, "17.fpga-gpu-ram-v2", "last-good", ["echo", "good"])
            update_build_record(active["status_path"], state="running", pid=1234)
            update_build_record(stale["status_path"], state="failed")
            update_build_record(success["status_path"], state="success")
            summary = clean_logs(root, keep=1, dry_run=True, yes=False)
            self.assertIn(str(stale["folder"]), summary["would_remove"])
            self.assertTrue(active["folder"].exists())
            self.assertTrue(success["folder"].exists())
            self.assertGreater(summary["bytes_freed"], 0)


if __name__ == "__main__":
    unittest.main()
