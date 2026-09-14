"""run-board: composición de board.py + resolución de prototipos, sin hardware."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import run_board
from backends import board


def fake_port(device, description="USB Serial", vid=run_board.FTDI_VENDOR_ID):
    return SimpleNamespace(device=device, description=description, vid=vid)


class DetectPortTest(unittest.TestCase):
    def test_picks_the_only_ftdi_port(self):
        ports = [fake_port("/dev/cu.usbserial-A", vid=run_board.FTDI_VENDOR_ID)]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            self.assertEqual(run_board.detect_port(), "/dev/cu.usbserial-A")

    def test_ignores_non_ftdi_ports(self):
        ports = [
            fake_port("/dev/cu.Bluetooth-Incoming-Port", vid=0x05AC),
            fake_port("/dev/cu.usbserial-B", vid=run_board.FTDI_VENDOR_ID),
        ]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            self.assertEqual(run_board.detect_port(), "/dev/cu.usbserial-B")

    def test_no_ftdi_ports_raises_clear_error(self):
        ports = [fake_port("/dev/cu.Bluetooth-Incoming-Port", vid=0x05AC)]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            with self.assertRaises(SystemExit):
                run_board.detect_port()

    def test_multiple_ftdi_ports_raises_clear_error(self):
        ports = [
            fake_port("/dev/cu.usbserial-A", vid=run_board.FTDI_VENDOR_ID),
            fake_port("/dev/cu.usbserial-B", vid=run_board.FTDI_VENDOR_ID),
        ]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            with self.assertRaises(SystemExit):
                run_board.detect_port()


class ResolveProgramTest(unittest.TestCase):
    def test_finds_program_in_examples_without_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            prototype_dir = Path(tmp)
            (prototype_dir / "examples").mkdir()
            program = prototype_dir / "examples" / "demo.asm"
            program.write_text("HALT\n", encoding="utf-8")
            found = run_board.resolve_program(prototype_dir, "demo")
            self.assertEqual(found, program.resolve())

    def test_absolute_path_is_used_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / "somewhere.asm"
            program.write_text("HALT\n", encoding="utf-8")
            found = run_board.resolve_program(Path(tmp), str(program))
            self.assertEqual(found, program.resolve())

    def test_missing_program_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                run_board.resolve_program(Path(tmp), "no-existe")

    def test_bare_name_falls_back_to_repo_wide_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prototype_dir = root / "6.fpga-cpu"
            prototype_dir.mkdir()
            other_dir = root / "x.tests" / "cases" / "basics"
            other_dir.mkdir(parents=True)
            program = other_dir / "vector.asm"
            program.write_text("HALT\n", encoding="utf-8")

            found = run_board.resolve_program(prototype_dir, "vector", root)
            self.assertEqual(found, program.resolve())

    def test_bare_name_without_root_does_not_search_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prototype_dir = root / "6.fpga-cpu"
            prototype_dir.mkdir()
            (root / "elsewhere.asm").write_text("HALT\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                run_board.resolve_program(prototype_dir, "elsewhere")

    def test_ambiguous_bare_name_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prototype_dir = root / "6.fpga-cpu"
            prototype_dir.mkdir()
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "dup.asm").write_text("HALT\n", encoding="utf-8")
            (root / "b" / "dup.asm").write_text("HALT\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                run_board.resolve_program(prototype_dir, "dup", root)

    def test_repo_wide_search_skips_venv_and_build_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prototype_dir = root / "6.fpga-cpu"
            prototype_dir.mkdir()
            ignored = root / ".venv" / "site-packages"
            ignored.mkdir(parents=True)
            (ignored / "noise.asm").write_text("HALT\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                run_board.resolve_program(prototype_dir, "noise", root)


class MainFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prototype_dir = Path(self.tmp.name) / "6.fpga-cpu"
        self.prototype_dir.mkdir()
        (self.prototype_dir / "monitor.py").write_text("", encoding="utf-8")

        patcher_repo = mock.patch.object(run_board, "find_repo_root", return_value=Path(self.tmp.name))
        patcher_resolve = mock.patch.object(run_board, "resolve_prototype", return_value=self.prototype_dir)
        patcher_monitor = mock.patch.object(run_board, "load_monitor", return_value=SimpleNamespace())
        self.addCleanup(patcher_repo.stop)
        self.addCleanup(patcher_resolve.stop)
        self.addCleanup(patcher_monitor.stop)
        patcher_repo.start()
        patcher_resolve.start()
        patcher_monitor.start()

    def test_board_not_connected_reports_error_and_exits_nonzero(self):
        with mock.patch.object(run_board, "_capabilities", return_value={}), \
             mock.patch.object(board, "read_monitor_version",
                               side_effect=board.BoardNotConnected("no hay placa")):
            code = run_board.main(["--prototype", "6", "--port", "COM3"])
        self.assertEqual(code, 1)

    def test_undeclared_prototype_warns_but_still_checks_connection(self):
        with mock.patch.object(run_board, "_capabilities", return_value={}), \
             mock.patch.object(board, "read_monitor_version") as read_version:
            code = run_board.main(["--prototype", "6", "--port", "COM3"])
        read_version.assert_called_once()
        self.assertEqual(code, 0)

    def test_declared_prototype_calls_ensure_bitstream_with_its_version(self):
        capability = {
            "monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga",
            "capabilities": ("mul_div",),
        }
        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "ensure_bitstream") as ensure:
            code = run_board.main(["--prototype", "6", "--port", "COM3"])
        ensure.assert_called_once()
        called_args = ensure.call_args.args
        self.assertEqual(called_args[3], (1, 16))  # expected version
        self.assertEqual(called_args[5], "fpga")   # backend
        self.assertEqual(called_args[6], "ebr")    # version_name
        self.assertEqual(code, 0)

    def test_bitstream_mismatch_reports_error_and_exits_nonzero(self):
        capability = {"monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga", "capabilities": ()}
        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "ensure_bitstream",
                               side_effect=board.BitstreamMismatch("otra version")):
            code = run_board.main(["--prototype", "6", "--port", "COM3"])
        self.assertEqual(code, 1)

    def test_program_flow_resets_writes_and_runs_in_order(self):
        binary = self.prototype_dir / "prog.bin"
        binary.write_bytes(b"\x00")
        capability = {"monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga", "capabilities": ()}
        calls = []

        def fake_cli(prototype_dir, port, *cli_args):
            calls.append(cli_args)
            return "CPU halted=True error=False"

        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "ensure_bitstream"), \
             mock.patch.object(run_board, "run_monitor_cli", side_effect=fake_cli):
            code = run_board.main([
                "--prototype", "6", "--port", "COM3", "--program", str(binary),
            ])

        self.assertEqual(code, 0)
        self.assertEqual(calls, [
            ("reset",),
            ("write-block", "0", str(binary.resolve())),
            ("run",),
            ("status",),
        ])

    def test_no_run_stops_before_the_run_command(self):
        binary = self.prototype_dir / "prog.bin"
        binary.write_bytes(b"\x00")
        capability = {"monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga", "capabilities": ()}
        calls = []

        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "ensure_bitstream"), \
             mock.patch.object(run_board, "run_monitor_cli", side_effect=lambda p, port, *a: calls.append(a)):
            code = run_board.main([
                "--prototype", "6", "--port", "COM3", "--program", str(binary), "--no-run",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(calls, [("reset",), ("write-block", "0", str(binary.resolve()))])

    def test_reset_flag_only_resets(self):
        capability = {"monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga", "capabilities": ()}
        calls = []

        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "ensure_bitstream"), \
             mock.patch.object(run_board, "run_monitor_cli", side_effect=lambda p, port, *a: calls.append(a)):
            code = run_board.main(["--prototype", "6", "--port", "COM3", "--reset"])

        self.assertEqual(code, 0)
        self.assertEqual(calls, [("reset",)])


class SeparateCommandsTest(unittest.TestCase):
    """board-info/board-upload/board-load: los mismos tres pasos que
    run-board, pero expuestos por separado (main_info/main_upload/main_load)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prototype_dir = Path(self.tmp.name) / "6.fpga-cpu"
        self.prototype_dir.mkdir()
        (self.prototype_dir / "monitor.py").write_text("", encoding="utf-8")

        patcher_repo = mock.patch.object(run_board, "find_repo_root", return_value=Path(self.tmp.name))
        patcher_resolve = mock.patch.object(run_board, "resolve_prototype", return_value=self.prototype_dir)
        patcher_monitor = mock.patch.object(run_board, "load_monitor", return_value=SimpleNamespace())
        self.addCleanup(patcher_repo.stop)
        self.addCleanup(patcher_resolve.stop)
        self.addCleanup(patcher_monitor.stop)
        patcher_repo.start()
        patcher_resolve.start()
        patcher_monitor.start()

    # -- board-info: nunca debe subir nada -----------------------------

    def test_info_matching_version_reports_ok_without_uploading(self):
        capability = {"monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga", "capabilities": ()}
        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "read_monitor_version", return_value=(1, 16)), \
             mock.patch.object(board, "upload") as upload, \
             mock.patch.object(board, "ensure_bitstream") as ensure:
            code = run_board.main_info(["--prototype", "6", "--port", "COM3"])
        self.assertEqual(code, 0)
        upload.assert_not_called()
        ensure.assert_not_called()

    def test_info_mismatch_reports_nonzero_without_uploading(self):
        capability = {"monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga", "capabilities": ()}
        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "read_monitor_version", return_value=(1, 1)), \
             mock.patch.object(board, "upload") as upload:
            code = run_board.main_info(["--prototype", "6", "--port", "COM3"])
        self.assertEqual(code, 1)
        upload.assert_not_called()

    def test_info_board_not_connected_reports_error(self):
        with mock.patch.object(run_board, "_capabilities", return_value={}), \
             mock.patch.object(board, "read_monitor_version",
                               side_effect=board.BoardNotConnected("no hay placa")):
            code = run_board.main_info(["--prototype", "6", "--port", "COM3"])
        self.assertEqual(code, 1)

    # -- board-upload: mismo comportamiento que el chequeo de run-board -

    def test_upload_calls_ensure_bitstream_with_declared_version(self):
        capability = {
            "monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga",
            "capabilities": ("mul_div",),
        }
        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "ensure_bitstream") as ensure:
            code = run_board.main_upload(["--prototype", "6", "--port", "COM3", "-y"])
        self.assertEqual(code, 0)
        ensure.assert_called_once()
        called_args = ensure.call_args.args
        self.assertEqual(called_args[3], (1, 16))
        policy = ensure.call_args.args[-1]
        self.assertTrue(policy.assume_yes)

    def test_upload_rebuild_forces_apio_upload_first(self):
        capability = {"monitor_version": (1, 16), "version_name": "ebr", "backend": "fpga", "capabilities": ()}
        with mock.patch.object(run_board, "_capabilities", return_value=capability), \
             mock.patch.object(board, "upload") as upload, \
             mock.patch.object(board, "ensure_bitstream"):
            code = run_board.main_upload(["--prototype", "6", "--port", "COM3", "--rebuild"])
        self.assertEqual(code, 0)
        upload.assert_called_once_with(self.prototype_dir)

    # -- board-load: nunca toca la identidad del bitstream --------------

    def test_load_does_not_check_bitstream_identity(self):
        binary = self.prototype_dir / "prog.bin"
        binary.write_bytes(b"\x00")
        calls = []
        with mock.patch.object(run_board, "_capabilities", return_value={}), \
             mock.patch.object(board, "ensure_bitstream") as ensure, \
             mock.patch.object(board, "read_monitor_version") as read_version, \
             mock.patch.object(run_board, "run_monitor_cli", side_effect=lambda p, port, *a: calls.append(a)):
            code = run_board.main_load([
                "--prototype", "6", "--port", "COM3", "--program", str(binary), "--no-run",
            ])
        self.assertEqual(code, 0)
        ensure.assert_not_called()
        read_version.assert_not_called()
        self.assertEqual(calls, [("reset",), ("write-block", "0", str(binary.resolve()))])


if __name__ == "__main__":
    unittest.main()
