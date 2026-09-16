#!/usr/bin/env python3
"""Gestor común de logs, estados y control de builds."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import PrototypeResolutionError, find_repo_root, resolve_prototype


BUILD_ROOT = Path(os.environ.get("MINI_GPU_ROOT", find_repo_root(Path.cwd()) if Path.cwd().exists() else Path(__file__).resolve().parents[1]))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_build_record(root: Path, prototype: str, label: str, command: list[str]) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rid = f"{timestamp}-{label}"
    folder = root / rid
    folder.mkdir(parents=True, exist_ok=True)
    status_path = folder / "status.json"
    payload = {
        "id": rid,
        "prototype": prototype,
        "label": label,
        "pid": None,
        "state": "running",
        "command": command,
        "started_at": utc_now(),
        "finished_at": None,
        "exit_code": None,
    }
    status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (folder / "build.log").write_text("", encoding="utf-8")
    return {"id": rid, "root": root, "folder": folder, "status_path": status_path, "record": payload}


def read_status(status_path: Path | str) -> dict:
    path = Path(status_path)
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def update_build_record(status_path: Path | str, **updates) -> dict:
    path = Path(status_path)
    data = read_status(path)
    data.update(updates)
    if updates.get("state") in {"success", "failed", "stopped"}:
        data["finished_at"] = utc_now()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def tail_log(log_path: Path | str, lines: int = 20) -> str:
    path = Path(log_path)
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if lines <= 0:
        return "\n".join(content)
    return "\n".join(content[-lines:])


def list_builds(root: Path | str) -> list[dict]:
    base = Path(root).resolve()
    if not base.exists():
        return []
    entries = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        status_path = child / "status.json"
        if not status_path.exists():
            continue
        try:
            record = read_status(status_path)
        except json.JSONDecodeError:
            continue
        record["folder"] = str(child)
        entries.append(record)
    return entries


def _parse_size(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().upper()
    if not text:
        return None
    units = {"B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    for suffix, multiplier in sorted(units.items(), key=lambda pair: len(pair[0]), reverse=True):
        if text.endswith(suffix):
            number = float(text[:-len(suffix)])
            return int(number * multiplier)
    return int(text)


def clean_logs(root: Path | str, keep: int = 10, older_than_days: int | None = None,
              max_size: str | int | None = None, prototype: str | None = None,
              dry_run: bool = True, yes: bool = False) -> dict:
    base = Path(root).resolve()
    entries = list_builds(base)
    if prototype:
        entries = [entry for entry in entries if entry.get("prototype") == prototype]
    entries = sorted(entries, key=lambda entry: entry.get("started_at", "1970-01-01T00:00:00Z"), reverse=True)
    keep_active = [entry for entry in entries if entry.get("state") == "running"]
    last_success = next((entry for entry in entries if entry.get("state") == "success"), None)
    newest = entries[0] if entries else None
    keep_ids = {entry.get("id") for entry in keep_active}
    if last_success:
        keep_ids.add(last_success.get("id"))
    if newest:
        keep_ids.add(newest.get("id"))
    for entry in entries[:keep]:
        keep_ids.add(entry.get("id"))
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        recent = [entry for entry in entries if entry.get("started_at") and datetime.fromisoformat(entry["started_at"].replace("Z", "+00:00")) >= cutoff]
        for entry in recent:
            keep_ids.add(entry.get("id"))
    candidates = []
    for entry in entries:
        entry_id = entry.get("id")
        if entry_id in keep_ids:
            continue
        if entry.get("state") == "running":
            continue
        candidates.append(entry)
    if max_size is not None:
        bounded = []
        for entry in candidates:
            folder = Path(entry["folder"])
            size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
            if size <= _parse_size(max_size):
                bounded.append(entry)
        candidates = bounded
    would_remove = [Path(entry["folder"]) for entry in candidates]
    bytes_freed = sum(sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) for path in would_remove)
    summary = {
        "dry_run": dry_run,
        "would_remove": [str(path) for path in would_remove],
        "removed": [],
        "bytes_freed": bytes_freed,
        "kept": sorted(keep_ids),
        "prototype": prototype,
        "keep": keep,
    }
    if dry_run or not yes:
        return summary
    for path in would_remove:
        if not path.exists():
            continue
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
        summary["removed"].append(str(path))
    summary["bytes_freed"] = bytes_freed
    return summary


def stop_build(status_path: Path | str) -> bool:
    path = Path(status_path)
    if not path.exists():
        return False
    payload = read_status(path)
    pid = payload.get("pid")
    if pid is None:
        update_build_record(path, state="stopped", exit_code=0)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        update_build_record(path, state="stopped", exit_code=143)
        return True
    except ProcessLookupError:
        update_build_record(path, state="stopped", exit_code=0)
        return False


def _run_and_track(command: list[str], cwd: Path, folder: Path, status_path: Path, echo: bool) -> int:
    proc = subprocess.Popen(
        command, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    update_build_record(status_path, pid=proc.pid)
    with (folder / "build.log").open("a", encoding="utf-8") as log_handle:
        for line in proc.stdout:
            log_handle.write(line)
            log_handle.flush()
            if echo:
                print(line, end="", flush=True)
    exit_code = proc.wait()
    if exit_code == 0:
        state = "success"
    elif exit_code < 0:
        # Negative return code means the process was killed by a signal,
        # which in this system only happens via build-stop.
        state = "stopped"
    else:
        state = "failed"
    update_build_record(status_path, state=state, exit_code=exit_code)
    return exit_code


class BuildRunner:
    @staticmethod
    def follow_log(log_path: Path | str, timeout: float = 1.0):
        path = Path(log_path)
        if not path.exists():
            yield ""
            return
        deadline = time.monotonic() + timeout
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            while time.monotonic() < deadline:
                lines = handle.readlines()
                for line in lines:
                    yield line.rstrip("\n")
                if not lines:
                    time.sleep(0.1)
            remaining = handle.readlines()
            for line in remaining:
                yield line.rstrip("\n")

    @staticmethod
    def run_background(command: list[str], root: Path, prototype: str, label: str) -> dict:
        record = create_build_record(root, prototype, label, command)
        status_path = record["status_path"]
        proc = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with (record["folder"] / "build.log").open("w", encoding="utf-8") as log_handle:
            while True:
                line = proc.stdout.readline() if proc.stdout else ""
                if not line and proc.poll() is not None:
                    break
                if line:
                    log_handle.write(line)
                    log_handle.flush()
                time.sleep(0.05)
        update_build_record(status_path, pid=proc.pid, state="success" if proc.returncode == 0 else "failed", exit_code=proc.returncode)
        return read_status(status_path)


def _get_latest_build(root: Path, prototype: str | None = None) -> dict | None:
    entries = list_builds(root)
    if prototype:
        entries = [entry for entry in entries if entry.get("prototype") == prototype]
    if not entries:
        return None
    return max(entries, key=lambda item: item.get("started_at", ""))


def _find_archived_report(log_file: Path) -> str | None:
    # build_report.py prints "Reports: <folder>" as its first line, pointing at
    # the per-prototype archive (hardware.pnr/sources.zip/metadata.json). That
    # folder's timestamp has microsecond precision and is unrelated to this
    # wrapper's own id, so without this there is no way to get from
    # `build-list`'s id to the archive path other than guessing it.
    if not log_file.exists():
        return None
    for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Reports: "):
            return line[len("Reports: "):].strip()
    return None


def _print_status_summary(record: dict) -> None:
    log_path = Path(record.get("log_path", ""))
    root = Path(record.get("root", "."))
    log_file = root / record.get("id", "") / "build.log"
    if log_file.exists():
        log_path = log_file
    print(f"Prototype: {record.get('prototype', 'unknown')}")
    print(f"Label: {record.get('label', 'build')}")
    print(f"State: {record.get('state', 'unknown')}")
    print(f"PID: {record.get('pid', 'n/a')}")
    archived_report = _find_archived_report(log_file)
    if archived_report:
        print(f"Archived report: {archived_report}")
    start = record.get("started_at")
    if start:
        try:
            started = datetime.fromisoformat(start.replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
            print(f"Elapsed: {int(elapsed.total_seconds() // 60):02d}:{int(elapsed.total_seconds() % 60):02d}")
        except ValueError:
            print("Elapsed: unknown")
    print(f"Log: {log_file}")
    if record.get("exit_code") is not None:
        print(f"Exit code: {record.get('exit_code')}")
    print("Recent output:")
    print(tail_log(log_file, 20) or "(empty log)")


def _main() -> int:
    parser = argparse.ArgumentParser(description="Herramientas de build y seguimiento.")
    subparsers = parser.add_subparsers(dest="command")

    status = subparsers.add_parser("status", help="Muestra el último build o uno concreto")
    status.add_argument("-p", "--prototype", default=None)
    status.add_argument("--id", default=None)
    status.add_argument("--root", type=Path, default=None)

    log_cmd = subparsers.add_parser("log", help="Muestra el log de un build")
    log_cmd.add_argument("-p", "--prototype", default=None)
    log_cmd.add_argument("--id", default=None)
    log_cmd.add_argument("--root", type=Path, default=None)
    log_cmd.add_argument("--lines", type=int, default=20)
    log_cmd.add_argument("--follow", action="store_true")

    list_cmd = subparsers.add_parser("list", help="Lista builds anteriores")
    list_cmd.add_argument("-p", "--prototype", default=None)
    list_cmd.add_argument("--root", type=Path, default=None)

    stop_cmd = subparsers.add_parser("stop", help="Detiene el build activo")
    stop_cmd.add_argument("-p", "--prototype", default=None)
    stop_cmd.add_argument("--id", default=None)
    stop_cmd.add_argument("--root", type=Path, default=None)

    clean_cmd = subparsers.add_parser("clean-logs", help="Limpia logs antiguos con seguridad")
    clean_cmd.add_argument("-p", "--prototype", default=None)
    clean_cmd.add_argument("--root", type=Path, default=None)
    clean_cmd.add_argument("--keep", type=int, default=10)
    clean_cmd.add_argument("--older-than", type=int, default=None)
    clean_cmd.add_argument("--max-size", default=None)
    clean_cmd.add_argument("--dry-run", action="store_true")
    clean_cmd.add_argument("--yes", action="store_true", default=False)

    run_cmd = subparsers.add_parser("run", help="Ejecuta y registra un comando de build")
    run_cmd.add_argument("-p", "--prototype", default="17")
    run_cmd.add_argument("--label", default="build")
    run_cmd.add_argument("--root", type=Path, default=None)
    run_cmd.add_argument("--background", action="store_true", help="Lanza el build en segundo plano y vuelve enseguida")
    run_cmd.add_argument("cmd_args", nargs=argparse.REMAINDER, metavar="command")

    build_cmd = subparsers.add_parser("build", help="Sintetiza con apio y archiva timing (tools/build_report.py)")
    build_cmd.add_argument("-p", "--prototype", required=True)
    build_cmd.add_argument("--label", default="build")
    build_cmd.add_argument("--root", type=Path, default=None)
    build_cmd.add_argument("--archive-only", action="store_true")
    build_cmd.add_argument("--incremental", action="store_true")
    build_cmd.add_argument("--background", action="store_true", help="Lanza el build en segundo plano y vuelve enseguida")

    test_cmd = subparsers.add_parser("test", help="Ejecuta la suite de un prototipo (tools/test_runner.py)")
    test_cmd.add_argument("-p", "--prototype", required=True)
    test_cmd.add_argument("--label", default="test")
    test_cmd.add_argument("--root", type=Path, default=None)
    test_cmd.add_argument("--quick", action="store_true", help="solo fixtures + tests Python, sin apio test")
    test_cmd.add_argument("--full", "--slow", dest="full", action="store_true",
                          help="incluye los bancos marcados TEST-LENTO (por defecto se omiten)")
    test_cmd.add_argument("--lint", action="store_true", help="añade apio lint")
    test_cmd.add_argument("--lint-only", action="store_true", help="solo apio lint, sin fixtures/tests/regresión RTL")
    test_cmd.add_argument("--verbose", action="store_true")
    test_cmd.add_argument("--background", action="store_true", help="Lanza el test en segundo plano y vuelve enseguida")

    sweep_cmd = subparsers.add_parser("sweep", help="Barrido de semillas de placement (tools/sweep_report.py)")
    sweep_cmd.add_argument("-p", "--prototype", required=True)
    sweep_cmd.add_argument("--label", default="sweep")
    sweep_cmd.add_argument("--root", type=Path, default=None)
    sweep_cmd.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    sweep_cmd.add_argument("--report-dir", type=Path, default=None)
    sweep_cmd.add_argument("--background", action="store_true", help="Lanza el barrido en segundo plano y vuelve enseguida")

    track_cmd = subparsers.add_parser("_track", help=argparse.SUPPRESS)
    track_cmd.add_argument("folder", type=Path)
    track_cmd.add_argument("status_path", type=Path)
    track_cmd.add_argument("cmd_args", nargs=argparse.REMAINDER, metavar="command")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    report_root = getattr(args, "root", None) or (find_repo_root(Path.cwd()) / "reports")
    if args.command == "list":
        entries = list_builds(report_root)
        if args.prototype:
            entries = [entry for entry in entries if entry.get("prototype") == args.prototype]
        if not entries:
            print("No builds found")
            return 0
        print(f"{'ID':<28} {'STATE':<8} {'AGE':<8} {'LABEL'}")
        now = datetime.now(timezone.utc)
        for entry in sorted(entries, key=lambda e: e.get("started_at", ""), reverse=True):
            started = datetime.fromisoformat(entry.get("started_at", "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
            age = now - started
            hours, remainder = divmod(int(age.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            if hours >= 24:
                age_str = f"{hours // 24}d"
            else:
                age_str = f"{hours:02d}:{minutes:02d}"
            print(f"{entry.get('id', 'unknown'):<28} {str(entry.get('state', 'unknown')).upper():<8} {age_str:<8} {entry.get('label', '')}")
        return 0

    if args.command == "status":
        if args.id:
            status_path = report_root / args.id / "status.json"
            record = read_status(status_path)
        else:
            record = _get_latest_build(report_root, args.prototype)
            if record is None:
                print("No builds found")
                return 1
        record["root"] = str(report_root)
        _print_status_summary(record)
        return 0

    if args.command == "log":
        if args.id:
            log_path = report_root / args.id / "build.log"
        else:
            record = _get_latest_build(report_root, args.prototype)
            if record is None:
                print("No builds found")
                return 1
            log_path = Path(record.get("folder") or report_root / record.get("id", "")) / "build.log"
        if args.follow:
            try:
                for line in BuildRunner.follow_log(log_path, timeout=60.0):
                    if line:
                        print(line)
            except KeyboardInterrupt:
                return 0
            return 0
        print(tail_log(log_path, args.lines))
        return 0

    if args.command == "stop":
        if args.id:
            status_path = report_root / args.id / "status.json"
            return 0 if stop_build(status_path) else 1
        record = _get_latest_build(report_root, args.prototype)
        if record is None:
            print("No running build found")
            return 1
        status_path = Path(record.get("folder")) / "status.json"
        return 0 if stop_build(status_path) else 1

    if args.command == "clean-logs":
        summary = clean_logs(report_root, keep=args.keep, older_than_days=args.older_than,
                            max_size=args.max_size, prototype=args.prototype,
                            dry_run=args.dry_run, yes=args.yes)
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "build":
        report_script = Path(__file__).resolve().with_name("build_report.py")
        command = [sys.executable, str(report_script), "--prototype", args.prototype, "--label", args.label]
        if args.archive_only:
            command.append("--archive-only")
        if args.incremental:
            command.append("--incremental")
        args.cmd_args = ["--", *command]
        args.command = "run"

    if args.command == "test":
        test_script = Path(__file__).resolve().with_name("test_runner.py")
        command = [sys.executable, str(test_script), "--prototype", args.prototype]
        if args.quick:
            command.append("--quick")
        if args.full:
            command.append("--full")
        if args.lint:
            command.append("--lint")
        if args.lint_only:
            command.append("--lint-only")
        if args.verbose:
            command.append("--verbose")
        args.cmd_args = ["--", *command]
        args.command = "run"

    if args.command == "sweep":
        sweep_script = Path(__file__).resolve().with_name("sweep_report.py")
        command = [sys.executable, str(sweep_script), "--prototype", args.prototype,
                  "--seeds", *(str(seed) for seed in args.seeds)]
        if args.report_dir is not None:
            command += ["--report-dir", str(args.report_dir)]
        args.cmd_args = ["--", *command]
        args.command = "run"

    if args.command == "run":
        command = args.cmd_args[1:] if args.cmd_args and args.cmd_args[0] == "--" else args.cmd_args
        if not command:
            parser.error("run requires a command, e.g.: run --prototype 17 -- apio build")
        report_root = args.root if args.root is not None else find_repo_root(Path.cwd()) / "reports"
        record = create_build_record(report_root, args.prototype, args.label, command)
        status_path = record["status_path"]
        if args.background:
            track_command = [
                sys.executable, "-m", "tools.build_runner", "_track",
                str(record["folder"]), str(status_path), "--", *command,
            ]
            kwargs: dict = {}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen(
                track_command, cwd=str(Path.cwd()),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                **kwargs,
            )
            print(f"Started build: {record['id']}")
            print(f"Status: {status_path}")
            print(f"Log: {record['folder'] / 'build.log'}")
            return 0
        return _run_and_track(command, Path.cwd(), record["folder"], status_path, echo=True)

    if args.command == "_track":
        command = args.cmd_args[1:] if args.cmd_args and args.cmd_args[0] == "--" else args.cmd_args
        return _run_and_track(command, Path.cwd(), args.folder, args.status_path, echo=False)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
