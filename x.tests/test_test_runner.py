"""tools/test_runner.py: qué pasos se saltan y cuáles se ejecutan según lo
que tenga cada prototipo, sin depender de apio ni de un board real."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import test_runner


class TestRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prototype_dir = self.root / "6.fpga-cpu"
        self.prototype_dir.mkdir()

        patcher_repo = mock.patch.object(test_runner, "find_repo_root", return_value=self.root)
        patcher_resolve = mock.patch.object(test_runner, "resolve_prototype", return_value=self.prototype_dir)
        patcher_apio = mock.patch.object(test_runner, "find_apio_binary", return_value="apio")
        self.addCleanup(patcher_repo.stop)
        self.addCleanup(patcher_resolve.stop)
        self.addCleanup(patcher_apio.stop)
        patcher_repo.start()
        patcher_resolve.start()
        patcher_apio.start()

    def _run(self, argv, returncode=0):
        completed = SimpleNamespace(returncode=returncode)
        with mock.patch.object(test_runner.subprocess, "run", return_value=completed) as run:
            code = test_runner.main(["--prototype", "6", *argv])
        return code, run

    def test_nothing_to_test_warns_and_succeeds(self):
        code, run = self._run([])
        self.assertEqual(code, 0)
        run.assert_not_called()

    def test_quick_skips_apio_test_even_with_apio_ini(self):
        (self.prototype_dir / "apio.ini").write_text("", encoding="utf-8")
        code, run = self._run(["--quick"])
        self.assertEqual(code, 0)
        run.assert_not_called()

    def test_python_tests_run_when_present(self):
        (self.prototype_dir / "test_foo.py").write_text("", encoding="utf-8")
        code, run = self._run(["--quick"])
        self.assertEqual(code, 0)
        run.assert_called_once()
        self.assertIn("unittest", run.call_args.args[0])

    def test_apio_test_runs_when_apio_ini_present_and_not_quick(self):
        (self.prototype_dir / "apio.ini").write_text("", encoding="utf-8")
        code, run = self._run([])
        self.assertEqual(code, 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["apio", "test", "-p", str(self.prototype_dir)])

    def test_lint_runs_apio_lint_in_addition_to_test(self):
        (self.prototype_dir / "apio.ini").write_text("", encoding="utf-8")
        code, run = self._run(["--lint"])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        lint_call = run.call_args_list[1]
        self.assertEqual(lint_call.args[0], ["apio", "lint", "-p", str(self.prototype_dir)])

    def test_lint_only_skips_fixtures_python_tests_and_rtl_regression(self):
        (self.prototype_dir / "make_fixtures.py").write_text("", encoding="utf-8")
        (self.prototype_dir / "test_foo.py").write_text("", encoding="utf-8")
        (self.prototype_dir / "apio.ini").write_text("", encoding="utf-8")
        code, run = self._run(["--lint-only"])
        self.assertEqual(code, 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["apio", "lint", "-p", str(self.prototype_dir)])

    def test_lint_without_apio_ini_warns_and_does_not_run(self):
        code, run = self._run(["--lint"])
        self.assertEqual(code, 0)
        run.assert_not_called()

    def test_fixtures_script_runs_before_python_tests(self):
        (self.prototype_dir / "make_fixtures.py").write_text("", encoding="utf-8")
        (self.prototype_dir / "test_foo.py").write_text("", encoding="utf-8")
        code, run = self._run(["--quick"])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("make_fixtures.py", run.call_args_list[0].args[0][1])

    def test_fixture_failure_stops_before_apio_test(self):
        (self.prototype_dir / "make_fixtures.py").write_text("", encoding="utf-8")
        (self.prototype_dir / "apio.ini").write_text("", encoding="utf-8")
        code, run = self._run([], returncode=1)
        self.assertEqual(code, 1)
        run.assert_called_once()  # solo las fixtures, nunca llega a apio test

    def test_python_test_failure_is_reported_but_other_steps_still_run(self):
        (self.prototype_dir / "test_foo.py").write_text("", encoding="utf-8")
        (self.prototype_dir / "apio.ini").write_text("", encoding="utf-8")
        code, run = self._run([], returncode=1)
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 2)  # tests Python (falla) + apio test (también falla)


if __name__ == "__main__":
    unittest.main()
