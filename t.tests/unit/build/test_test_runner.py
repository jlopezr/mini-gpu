"""tools/test_runner.py: qué pasos se saltan y cuáles se ejecutan según lo
que tenga cada prototipo, sin depender de apio ni de un board real."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import test_runner


class RunnerBase(unittest.TestCase):
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


class TestRunnerTest(RunnerBase):
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


class ParallelRtlTest(RunnerBase):
    """Con varios bancos, `apio test` se reparte en grupos que corren en copias."""

    def setUp(self):
        super().setUp()
        (self.prototype_dir / "apio.ini").write_text("", encoding="utf-8")
        for name in ("a_tb.v", "b_tb.v", "c_tb.v", "d_tb.v"):
            (self.prototype_dir / name).write_text("// banco", encoding="utf-8")
        (self.prototype_dir / "cpu.v").write_text("// fuente", encoding="utf-8")
        (self.prototype_dir / "reports").mkdir()
        (self.prototype_dir / "reports" / "pesado.bin").write_text("x", encoding="utf-8")
        self.seen = []

    def _fake_run(self, returncode_for=None, write_file=None):
        """subprocess.run falso que mira la copia desde la que se le llama."""
        def fake(command, cwd=None, **kwargs):
            work = Path(cwd)
            self.seen.append(dict(
                command=command, cwd=work,
                benches=sorted(p.name for p in work.glob("*_tb.v")),
                has_cpu=(work / "cpu.v").exists(),
                has_reports=(work / "reports").exists()))
            if write_file:
                (work / write_file).write_text("volcado", encoding="utf-8")
            code = (returncode_for or (lambda w: 0))(work)
            return SimpleNamespace(returncode=code, stdout="salida apio\n", stderr="")
        return fake

    def _main(self, argv, **kw):
        with mock.patch.object(test_runner.subprocess, "run", side_effect=self._fake_run(**kw)):
            return test_runner.main(["--prototype", "6", *argv])

    def test_reparte_los_bancos_por_turnos_en_copias_aisladas(self):
        self.assertEqual(self._main(["--jobs", "2"]), 0)
        self.assertEqual(len(self.seen), 2)
        self.assertCountEqual([s["benches"] for s in self.seen],
                              [["a_tb.v", "c_tb.v"], ["b_tb.v", "d_tb.v"]])
        for s in self.seen:
            self.assertNotEqual(s["cwd"], self.prototype_dir)          # no la carpeta real
            self.assertEqual(s["cwd"].parent, self.root)               # hermana
            self.assertFalse(s["cwd"].name[0].isdigit())               # no confunde `-p 6`
            self.assertEqual(s["command"], ["apio", "test", "-p", str(s["cwd"])])
            self.assertTrue(s["has_cpu"])
            self.assertFalse(s["has_reports"])                         # no se copia el historial

    def test_no_deja_copias_sobrantes(self):
        self._main(["--jobs", "2"])
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(test_runner.TEMP_PREFIX)], [])

    def test_no_deja_copias_sobrantes_ni_con_fallo(self):
        self.assertEqual(self._main(["--jobs", "2"], returncode_for=lambda w: 1), 1)
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(test_runner.TEMP_PREFIX)], [])

    def test_un_grupo_que_falla_hace_fallar_la_suite_y_el_otro_se_ejecuta(self):
        code = self._main(["--jobs", "2"], returncode_for=lambda w: 1 if "0_" in w.name else 0)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.seen), 2)

    def test_jobs_1_es_una_sola_invocacion_sobre_la_carpeta_real(self):
        with mock.patch.object(test_runner.subprocess, "run",
                               return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(test_runner.main(["--prototype", "6", "--jobs", "1"]), 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["apio", "test", "-p", str(self.prototype_dir)])

    def test_los_bancos_lentos_se_omiten_salvo_con_full(self):
        (self.prototype_dir / "d_tb.v").write_text("// TEST-LENTO: tarda mucho", encoding="utf-8")
        self._main(["--jobs", "2"])
        self.assertEqual(sorted(b for s in self.seen for b in s["benches"]), ["a_tb.v", "b_tb.v", "c_tb.v"])
        self.seen.clear()
        self._main(["--jobs", "2", "--full"])
        self.assertEqual(sorted(b for s in self.seen for b in s["benches"]),
                         ["a_tb.v", "b_tb.v", "c_tb.v", "d_tb.v"])

    def test_devuelve_los_ficheros_que_un_banco_escribe_en_su_carpeta(self):
        self._main(["--jobs", "2"], write_file="frame_full.bin")
        self.assertEqual((self.prototype_dir / "frame_full.bin").read_text(encoding="utf-8"), "volcado")

    def test_no_devuelve_ficheros_que_no_ha_tocado_nadie(self):
        (self.prototype_dir / "cpu.v").write_text("// original", encoding="utf-8")
        self._main(["--jobs", "2"])
        self.assertEqual((self.prototype_dir / "cpu.v").read_text(encoding="utf-8"), "// original")

    def test_jobs_menor_que_uno_es_un_error(self):
        with self.assertRaises(SystemExit):
            test_runner.main(["--prototype", "6", "--jobs", "0"])


if __name__ == "__main__":
    unittest.main()
