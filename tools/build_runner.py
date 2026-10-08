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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import (
    PrototypeResolutionError,
    find_repo_root,
    list_prototypes,
    resolve_prototype,
)


BUILD_ROOT = Path(os.environ.get("MINI_GPU_ROOT", find_repo_root(Path.cwd()) if Path.cwd().exists() else Path(__file__).resolve().parents[1]))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_prototype(value: str | None) -> str | None:
    """Nombre canonico de carpeta para un prototipo, o el valor tal cual.

    El registro guardaba lo que hubieras escrito en -p, asi que el MISMO
    prototipo aparecia como '22' y como '22.fpga-gpu-bl8' segun quien lanzara el
    build, y filtrar por -p se dejaba fuera la mitad de su historial. Se
    normalizan los dos lados de la comparacion, no solo lo que se escribe nuevo:
    asi los registros viejos siguen encontrandose sin reescribirlos.
    """
    if not value:
        return value
    try:
        return resolve_prototype(value, root=BUILD_ROOT).name
    except (PrototypeResolutionError, OSError):
        return value


def create_build_record(root: Path, prototype: str, label: str, command: list[str]) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Microsegundos y no segundos, y `exist_ok=False`: con segundos, dos builds
    # lanzados en paralelo en el MISMO segundo generaban el mismo id, y como la
    # carpeta se creaba con exist_ok=True acababan compartiendo status.json y
    # build.log sin que nada se quejara. Se pisaban el fichero de estado a medio
    # escribir y el segundo moria con un JSONDecodeError antes de sintetizar
    # nada. La carpeta archivada ya usaba microsegundos; esta se habia quedado
    # atras. Si aun asi colisionan, se desempata con el PID en vez de compartir.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    rid = f"{timestamp}-{label}"
    folder = root / rid
    intento = 0
    while True:
        try:
            folder.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            intento += 1
            rid = f"{timestamp}-{os.getpid()}-{intento}-{label}"
            folder = root / rid
    status_path = folder / "status.json"
    payload = {
        "id": rid,
        "prototype": normalize_prototype(prototype),
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
    if updates.get("state") in {"success", "failed", "stopped", "interrupted"}:
        data["finished_at"] = utc_now()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def process_exists(pid: int) -> bool:
    """Return whether *pid* currently names a process.

    Signal 0 does not terminate the process.  It only asks the operating
    system to validate the PID; lack of permission still proves that the
    process exists.
    """
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5  # ACCESS_DENIED also proves it exists
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Windows reports an invalid/dead PID as a generic OSError rather than
        # ProcessLookupError on some Python versions.
        return False
    return True


def reconcile_build_record(status_path: Path | str, record: dict) -> dict:
    """Persist an interrupted state when a recorded build process is gone."""
    pid = record.get("pid")
    if record.get("state") != "running" or pid is None:
        return record
    try:
        alive = process_exists(int(pid))
    except (TypeError, ValueError):
        alive = False
    if alive:
        return record
    return update_build_record(status_path, state="interrupted")


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
        record = reconcile_build_record(status_path, record)
        record["folder"] = str(child)
        entries.append(record)
    return entries


def buildable_prototypes(repo_root: Path) -> list[Path]:
    """Return prototype directories that declare an Apio project."""
    return [path for path in list_prototypes(repo_root) if (path / "apio.ini").is_file()]


def bitstream_status(prototype: Path) -> str:
    """Return CURRENT, STALE or MISSING for a prototype's default Apio env."""
    from tools.build_report import bitstream_is_current, default_env

    bitstream = prototype / "_build" / default_env(prototype) / "hardware.bit"
    if not bitstream.is_file():
        return "MISSING"
    return "CURRENT" if bitstream_is_current(prototype) else "STALE"


def _build_archive(record: dict, prototype: Path) -> Path | None:
    folder_text = record.get("folder")
    folder = Path(folder_text) if folder_text else None
    archived = _find_archived_report(folder / "build.log") if folder else None
    if archived:
        path = Path(archived)
        if path.exists():
            return path
    archives = sorted((prototype / "reports").glob("*/metadata.json"))
    return archives[-1].parent if archives else None


def _record_from_archive(archive: Path, timing: str) -> dict:
    try:
        metadata = json.loads((archive / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    exit_code = metadata.get("exit_code")
    successful = exit_code == 0 and timing != "FAIL"
    return {
        "state": "success" if successful else "failed",
        "started_at": metadata.get("started", "-"),
        "label": metadata.get("label", "build"),
        "exit_code": exit_code,
    }


def _elapsed_text(record: dict, archive: Path | None) -> str:
    if archive is not None:
        metadata_path = archive / "metadata.json"
        try:
            seconds = float(json.loads(metadata_path.read_text(encoding="utf-8"))["elapsed_seconds"])
            return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    try:
        started = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
        end_text = record.get("finished_at")
        ended = (datetime.fromisoformat(end_text.replace("Z", "+00:00"))
                 if end_text else datetime.now(timezone.utc))
        seconds = max(0, int((ended - started).total_seconds()))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    except (KeyError, AttributeError, TypeError, ValueError):
        return "-"


def _timing_text(archive: Path | None) -> tuple[str, str]:
    if archive is None:
        return "-", "-"
    try:
        summary = json.loads((archive / "summary.json").read_text(encoding="utf-8"))
        clocks = summary.get("clocks", {})
    except (OSError, json.JSONDecodeError):
        return "-", "-"
    if not clocks:
        return "-", "-"
    passes = all(values.get("achieved", 0) >= values.get("constraint", 0)
                 for values in clocks.values())
    limiting = min(clocks.values(), key=lambda values:
                   values.get("achieved", 0) / max(values.get("constraint", 0), 0.001))
    fmax = f"{limiting.get('achieved', 0):.1f}/{limiting.get('constraint', 0):.1f}"
    return "PASS" if passes else "FAIL", fmax


def _clock_short_name(name: str) -> str:
    """`$glbnet$sdram_clk$TRELLIS_IO_OUT` -> `sdram_clk`."""
    return name.removeprefix("$glbnet$").split("$")[0]


def _clock_details(archive: Path | None) -> list[tuple[str, float, float]]:
    """Todos los relojes del ultimo informe: (nombre, alcanzado, exigido).

    Ordenados de menos a mas margen, asi el primero es el que limita."""
    if archive is None:
        return []
    try:
        clocks = json.loads((archive / "summary.json").read_text(encoding="utf-8")).get("clocks", {})
    except (OSError, json.JSONDecodeError):
        return []
    rows = [(_clock_short_name(name), float(values.get("achieved", 0)),
             float(values.get("constraint", 0))) for name, values in clocks.items()]
    return sorted(rows, key=lambda row: row[1] / max(row[2], 0.001))


def _local_date_text(value: str | None) -> str:
    """Format an ISO timestamp in the computer's local time zone."""
    if not value or value == "-":
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        local = parsed.astimezone()
    except (ValueError, TypeError):
        return "-"
    return f"{local:%Y-%m-%d %H:%M}"


def prototype_build_summary(repo_root: Path, report_root: Path,
                            prototype: str | None = None) -> list[dict]:
    """Aggregate build history and local artifacts without starting builds."""
    from tools.build_report import configured_seed

    entries = list_builds(report_root)
    latest: dict[str, dict] = {}
    for entry in entries:
        # LAST BUILD habla de sintesis, no de pruebas: un `test` (lint o suite)
        # que acaba FAILED no debe tapar un build bueno. Se mantiene si sigue
        # en marcha, para que el aviso de ACTIVE BUILD lo siga mostrando.
        if entry.get("label") == "test" and str(entry.get("state", "")).lower() != "running":
            continue
        name = normalize_prototype(entry.get("prototype"))
        if name and (name not in latest or entry.get("started_at", "") > latest[name].get("started_at", "")):
            latest[name] = entry
    wanted = normalize_prototype(prototype) if prototype else None
    rows = []
    for path in buildable_prototypes(repo_root):
        if wanted and path.name != wanted:
            continue
        record = latest.get(path.name)
        archive = _build_archive(record, path) if record else _build_archive({}, path)
        timing, fmax = _timing_text(archive)
        if record is None and archive is not None:
            record = _record_from_archive(archive, timing) or None
        state = str(record.get("state", "never")).upper() if record else "NEVER"
        if state == "FAILED" and timing == "FAIL":
            state = "TIMING_FAIL"
        rows.append({
            "prototype": path.name,
            "bitstream": bitstream_status(path),
            "state": state,
            "timing": timing,
            "fmax": fmax,
            "clocks": _clock_details(archive),
            "seed": str(configured_seed(path) or "-"),
            "elapsed": _elapsed_text(record, archive) if record else "-",
            "date": _local_date_text(record.get("started_at")) if record else "-",
            "label": record.get("label", "-") if record else "-",
        })
    return rows


def format_build_list(entries: list[dict], now: datetime) -> list[str]:
    """Tabla de `list`: el ancho de ID sale del ID mas largo, no de uno fijo.

    Con un ancho fijo, un ID con etiqueta larga (`...-mmio-rd-stage`) desplazaba
    el resto de las columnas de su fila.
    """
    rows = []
    for entry in sorted(entries, key=lambda e: e.get("started_at", ""), reverse=True):
        started = datetime.fromisoformat(
            entry.get("started_at", "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
        hours, remainder = divmod(int((now - started).total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        age = f"{hours // 24}d" if hours >= 24 else f"{hours:02d}:{minutes:02d}"
        rows.append((str(entry.get("id", "unknown")),
                     str(entry.get("state", "unknown")).upper(), age,
                     str(entry.get("label", ""))))
    width_id = max([len("ID"), *(len(row[0]) for row in rows)])
    width_state = max([len("STATE"), *(len(row[1]) for row in rows)])
    width_age = max([len("AGE"), *(len(row[2]) for row in rows)])
    lines = [f"{'ID':<{width_id}}  {'STATE':<{width_state}}  {'AGE':<{width_age}}  LABEL"]
    lines += [f"{i:<{width_id}}  {s:<{width_state}}  {a:<{width_age}}  {label}"
              for i, s, a, label in rows]
    return lines


def print_prototype_build_summary(rows: list[dict]) -> None:
    use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    colors = {
        "CURRENT": "32", "SUCCESS": "32", "PASS": "32",
        "STALE": "33", "INTERRUPTED": "33", "TIMING_FAIL": "33", "RUNNING": "36",
        "MISSING": "31", "FAILED": "31", "FAIL": "31",
        "NEVER": "2",
    }

    def field(value: str, width: int) -> str:
        padded = f"{value:<{width}}"
        code = colors.get(value)
        return f"\033[{code}m{padded}\033[0m" if use_color and code else padded

    active = [row["prototype"] for row in rows if row["state"] == "RUNNING"]
    if active:
        message = "ACTIVE BUILD" if len(active) == 1 else "ACTIVE BUILDS"
        text = f"{message}: {', '.join(active)}"
        print(f"\033[36;1m{text}\033[0m" if use_color else text)
    # El ancho de cada columna sale de sus valores, no de uno fijo: un nombre de
    # prototipo o de reloj mas largo de lo previsto desalineaba el resto de la fila.
    def widest(header: str, values) -> int:
        return max([len(header), *(len(str(value)) for value in values)])

    def fmax_text(row: dict, clock: tuple) -> str:
        return f"{clock[1]:.1f}/{clock[2]:.1f}"

    w_proto = widest("PROTOTYPE", (row["prototype"] for row in rows))
    w_bit = widest("BITSTREAM", (row["bitstream"] for row in rows))
    w_state = widest("LAST BUILD", (row["state"] for row in rows))
    w_timing = widest("TIMING", (row["timing"] for row in rows))
    w_seed = widest("SEED", (row["seed"] for row in rows))
    w_clock = widest("CLOCK", (clock[0] for row in rows for clock in row.get("clocks", [])))
    w_clock = max(w_clock, widest("CLOCK", ("-",)))
    w_fmax = widest("FMAX/REQ", (fmax_text(row, clock) if row.get("clocks") else row["fmax"]
                                 for row in rows for clock in (row.get("clocks") or [None])[:1]))
    w_elapsed = widest("ELAPSED", (row["elapsed"] for row in rows))
    w_date = widest("DATE", (row["date"] for row in rows))
    print(f"  {'PROTOTYPE':<{w_proto}} {'BITSTREAM':<{w_bit}} {'LAST BUILD':<{w_state}} "
          f"{'TIMING':<{w_timing}} {'SEED':<{w_seed}} {'CLOCK':<{w_clock}} "
          f"{'FMAX/REQ':<{w_fmax}} {'ELAPSED':<{w_elapsed}} {'DATE':<{w_date}} LABEL")
    for row in rows:
        marker = "*" if row["state"] == "RUNNING" else " "
        # Un reloj por linea. El primero es el que limita (el de menos margen) y
        # va en la fila del prototipo, junto al PASS/FAIL general; el resto,
        # debajo, en las mismas columnas CLOCK / FMAX/REQ. El valor de un reloj
        # que no cumple es lo que sale en rojo.
        def clock_value(achieved: float, required: float, width: int) -> str:
            text = f"{achieved:.1f}/{required:.1f}"
            padded = f"{text:<{width}}"
            return (f"\033[31m{padded}\033[0m"
                    if use_color and achieved < required else padded)

        clocks = row.get("clocks", [])
        if clocks:
            name, achieved, required = clocks[0]
            clock_name, fmax = name, clock_value(achieved, required, w_fmax)
        else:
            clock_name, fmax = "-", f"{row['fmax']:<{w_fmax}}"
        print(f"{marker} {row['prototype']:<{w_proto}} {field(row['bitstream'], w_bit)} "
              f"{field(row['state'], w_state)} {field(row['timing'], w_timing)} "
              f"{row['seed']:<{w_seed}} {clock_name:<{w_clock}} {fmax} "
              f"{row['elapsed']:<{w_elapsed}} {row['date']:<{w_date}} {row['label']}")
        for name, achieved, required in clocks[1:]:
            print(f"  {'':<{w_proto}} {'':<{w_bit}} {'':<{w_state}} {'':<{w_timing}} "
                  f"{'':<{w_seed}} {name:<{w_clock}} "
                  f"{clock_value(achieved, required, 0)}")


def build_all(repo_root: Path, *, label: str = "build", archive_only: bool = False,
              incremental: bool | None = None, run=subprocess.run) -> int:
    """Build every Apio prototype sequentially and keep going after failures."""
    prototypes = buildable_prototypes(repo_root)
    if not prototypes:
        print("No buildable prototypes found")
        return 0
    results: list[tuple[str, int]] = []
    for index, prototype in enumerate(prototypes, 1):
        print(f"\n== [{index}/{len(prototypes)}] {prototype.name} ==", flush=True)
        command = [
            sys.executable, "-m", "tools.build_runner", "build",
            "--prototype", prototype.name, "--label", label,
        ]
        if archive_only:
            command.append("--archive-only")
        if incremental is not None:
            command.append("--incremental" if incremental else "--no-incremental")
        completed = run(command, cwd=repo_root)
        results.append((prototype.name, completed.returncode))

    print("\n== build --all summary ==")
    for name, returncode in results:
        print(f"{'SUCCESS' if returncode == 0 else 'FAILED':<8} {name}")
    failed = sum(returncode != 0 for _, returncode in results)
    print(f"{len(results) - failed} successful, {failed} failed")
    return 1 if failed else 0


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
        wanted = normalize_prototype(prototype)
        entries = [entry for entry in entries
                   if normalize_prototype(entry.get("prototype")) == wanted]
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


HEAVY_ARCHIVE_FILES = ("hardware.json", "hardware.config", "hardware.pnr")


def _archive_timing_ok(archive: Path) -> bool:
    """True si el archivo terminó bien y todos sus relojes cumplen."""
    try:
        metadata = json.loads((archive / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if metadata.get("exit_code") != 0:
        return False
    try:
        summary = json.loads((archive / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return all(clock.get("achieved", 0) >= clock.get("constraint", 0)
               for clock in summary.get("clocks", {}).values())


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _remove_tree(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def clean_reports(repo_root: Path | str, keep: int = 2, prototype: str | None = None,
                  full: bool = False, dry_run: bool = True, yes: bool = False) -> dict:
    """Aligera los archivos de build de `<prototipo>/reports/`.

    Se conservan intactos los `keep` más recientes, el último que cumplió timing
    y los que no tienen `metadata.json` (build en curso). En el resto se borran
    los ficheros pesados y los `sweep-*`; con `full`, la carpeta entera.
    """
    base = Path(repo_root).resolve()
    prototypes = buildable_prototypes(base)
    if prototype:
        wanted = normalize_prototype(prototype)
        prototypes = [p for p in prototypes if normalize_prototype(p.name) == wanted]
    would_remove: list[Path] = []
    kept: list[str] = []
    for proto in prototypes:
        reports = proto / "reports"
        archives = sorted(p for p in reports.glob("*") if p.is_dir()) if reports.is_dir() else []
        protected = set(archives[-keep:]) if keep > 0 else set()
        protected.update(p for p in archives if not (p / "metadata.json").exists())
        last_ok = next((p for p in reversed(archives) if _archive_timing_ok(p)), None)
        if last_ok is not None:
            protected.add(last_ok)
        for archive in archives:
            if archive in protected:
                kept.append(str(archive))
            elif full:
                would_remove.append(archive)
            else:
                would_remove.extend(p for p in archive.iterdir()
                                    if p.name in HEAVY_ARCHIVE_FILES
                                    or (p.is_dir() and p.name.startswith("sweep-")))
    bytes_freed = sum(_tree_size(p) for p in would_remove)
    summary = {
        "dry_run": dry_run or not yes,
        "would_remove": [str(p) for p in would_remove],
        "removed": [],
        "bytes_freed": bytes_freed,
        "kept": sorted(kept),
        "prototype": prototype,
        "keep": keep,
        "full": full,
    }
    if dry_run or not yes:
        return summary
    for path in would_remove:
        if path.exists():
            _remove_tree(path)
            summary["removed"].append(str(path))
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
        wanted = normalize_prototype(prototype)
        entries = [entry for entry in entries
                   if normalize_prototype(entry.get("prototype")) == wanted]
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
    root = Path(record.get("root", "."))
    log_file = root / record.get("id", "") / "build.log"
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
    list_cmd.add_argument("--prototypes", action="store_true",
                          help="resume el estado de cada prototipo construible")

    stop_cmd = subparsers.add_parser("stop", help="Detiene el build activo")
    stop_cmd.add_argument("-p", "--prototype", default=None)
    stop_cmd.add_argument("--id", default=None)
    stop_cmd.add_argument("--root", type=Path, default=None)

    clean_cmd = subparsers.add_parser(
        "clean", help="Limpia logs y reports antiguos con seguridad")
    clean_cmd.add_argument("-p", "--prototype", default=None)
    clean_cmd.add_argument("--root", type=Path, default=None,
                           help="carpeta de logs de ejecución (por defecto reports/ de la raíz)")
    clean_cmd.add_argument("--keep", type=int, default=10,
                           help="logs de ejecución que se conservan")
    clean_cmd.add_argument("--keep-reports", type=int, default=2,
                           help="archivos de build por prototipo que se conservan completos")
    clean_cmd.add_argument("--full", action="store_true",
                           help="borra los reports viejos enteros, no solo lo pesado")
    clean_cmd.add_argument("--older-than", type=int, default=None, help="solo logs")
    clean_cmd.add_argument("--max-size", default=None, help="solo logs")
    clean_cmd.add_argument("--dry-run", action="store_true")
    clean_cmd.add_argument("--yes", action="store_true", default=False)

    run_cmd = subparsers.add_parser("run", help="Ejecuta y registra un comando de build")
    run_cmd.add_argument("-p", "--prototype", default="17")
    run_cmd.add_argument("--label", default="build")
    run_cmd.add_argument("--root", type=Path, default=None)
    run_cmd.add_argument("--background", action="store_true", help="Lanza el build en segundo plano y vuelve enseguida")
    run_cmd.add_argument("cmd_args", nargs=argparse.REMAINDER, metavar="command")

    build_cmd = subparsers.add_parser("build", help="Sintetiza con apio y archiva timing (tools/build_report.py)")
    build_target = build_cmd.add_mutually_exclusive_group(required=True)
    build_target.add_argument("-p", "--prototype")
    build_target.add_argument("--all", action="store_true", help="construye secuencialmente todos los prototipos con apio.ini")
    build_cmd.add_argument("--label", default="build")
    build_cmd.add_argument("--root", type=Path, default=None)
    build_cmd.add_argument("--archive-only", action="store_true")
    build_cache = build_cmd.add_mutually_exclusive_group()
    build_cache.add_argument("--incremental", dest="incremental", action="store_true",
                             help="fuerza una ejecución usando la caché normal de Apio")
    build_cache.add_argument("--no-incremental", dest="incremental", action="store_false",
                             help="fuerza PNR detallado y regenera el routing")
    build_cmd.set_defaults(incremental=None)
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
    test_cmd.add_argument("--jobs", type=int, default=None,
                          help="Grupos de bancos RTL en paralelo (por defecto 2; 1 = como antes)")
    test_cmd.add_argument("--background", action="store_true", help="Lanza el test en segundo plano y vuelve enseguida")

    sweep_cmd = subparsers.add_parser("sweep", help="Barrido de semillas de placement (tools/sweep_report.py)")
    sweep_cmd.add_argument("-p", "--prototype", help="obligatorio salvo con --last")
    sweep_cmd.add_argument("--last", action="store_true",
                           help="Resumen del último barrido de cada prototipo que tenga alguno")
    sweep_cmd.add_argument("--label", default="sweep")
    sweep_cmd.add_argument("--root", type=Path, default=None)
    sweep_cmd.add_argument("--seeds", type=int, nargs="+", default=None,
                           help="Semillas a barrer (por defecto 1 2 3 4 5)")
    sweep_cmd.add_argument("--report-dir", type=Path, default=None)
    sweep_cmd.add_argument("--compare", type=Path, default=None, metavar="SWEEP",
                           help="Carpeta sweep-* de un barrido anterior con las mismas semillas")
    sweep_cmd.add_argument("--list", action="store_true",
                           help="Lista los barridos ya hechos del prototipo")
    sweep_cmd.add_argument("--show", metavar="SWEEP", default=None,
                           help="Detalle por semilla de un barrido (latest, trozo del nombre o ruta)")
    sweep_cmd.add_argument("--promote", nargs="?", const="best", default=None, metavar="SEMILLA",
                           help="Adopta una semilla: la escribe en el apio.ini y la deja como build "
                                "archivado y bitstream, sin sintetizar. Sin valor, la de más margen. "
                                "Con --seeds actúa al terminar el barrido; sin --seeds, sobre el último "
                                "barrido (o el de --from)")
    sweep_cmd.add_argument("--from", dest="from_sweep", default="latest", metavar="SWEEP",
                           help="Barrido del que promover (por defecto el último)")
    sweep_cmd.add_argument("--nextpnr-options", nargs="+", default=[], metavar="OPCION",
                           help="Opciones extra de nextpnr sin guiones y con = para el valor, "
                                "p. ej. tmg-ripup placer-heap-timingweight=30")
    sweep_cmd.add_argument("--jobs", type=int, default=None,
                           help="Semillas en paralelo (por defecto, un tercio de los hilos de la máquina)")
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
        if args.prototypes:
            repo_root = find_repo_root(Path.cwd())
            rows = prototype_build_summary(repo_root, report_root, args.prototype)
            print_prototype_build_summary(rows)
            return 0
        entries = list_builds(report_root)
        if args.prototype:
            entries = [entry for entry in entries if entry.get("prototype") == args.prototype]
        if not entries:
            print("No builds found")
            return 0
        print("\n".join(format_build_list(entries, datetime.now(timezone.utc))))
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
        archived_report = _find_archived_report(log_path)
        if archived_report:
            detailed_log = Path(archived_report) / "build.log"
            if detailed_log.is_file():
                log_path = detailed_log
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

    if args.command == "clean":
        logs = clean_logs(report_root, keep=args.keep, older_than_days=args.older_than,
                          max_size=args.max_size, prototype=args.prototype,
                          dry_run=args.dry_run, yes=args.yes)
        reports = clean_reports(find_repo_root(Path.cwd()), keep=args.keep_reports,
                                prototype=args.prototype, full=args.full,
                                dry_run=args.dry_run, yes=args.yes)
        print(json.dumps({"logs": logs, "reports": reports}, indent=2))
        freed = logs["bytes_freed"] + reports["bytes_freed"]
        verb = "liberaría" if args.dry_run or not args.yes else "liberados"
        print(f"{verb} {freed / 1024 ** 2:.0f} MB", file=sys.stderr)
        return 0

    if args.command == "build":
        if args.all:
            if args.background:
                parser.error("build --all no admite --background; los builds se ejecutan secuencialmente")
            repo_root = find_repo_root(Path.cwd())
            return build_all(repo_root, label=args.label,
                             archive_only=args.archive_only,
                             incremental=args.incremental)
        report_script = Path(__file__).resolve().with_name("build_report.py")
        command = [sys.executable, str(report_script), "--prototype", args.prototype, "--label", args.label]
        if args.archive_only:
            command.append("--archive-only")
        if args.incremental is not None:
            command.append("--incremental" if args.incremental else "--no-incremental")
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
        if args.jobs is not None:
            command += ["--jobs", str(args.jobs)]
        args.cmd_args = ["--", *command]
        args.command = "run"

    promote_only = args.command == "sweep" and args.promote is not None and args.seeds is None
    if args.command == "sweep" and (args.last or args.list or args.show is not None
                                    or promote_only):
        # Solo consulta o adopción de un barrido ya hecho (segundos): no es un
        # build, así que no crea registro en reports/.
        sweep_script = Path(__file__).resolve().with_name("sweep_report.py")
        query = [sys.executable, str(sweep_script)]
        if args.last:
            query.append("--last")
        else:
            if args.prototype is None:
                parser.error("--list/--show/--promote necesitan --prototype")
            query += ["--prototype", args.prototype]
            if promote_only:
                query += ["--promote", args.promote, "--from", args.from_sweep]
            else:
                query += ["--list"] if args.list else ["--show", args.show]
        return subprocess.run(query, cwd=Path.cwd()).returncode

    if args.command == "sweep" and args.prototype is None:
        parser.error("sweep necesita --prototype (salvo con --last)")

    if args.command == "sweep":
        sweep_script = Path(__file__).resolve().with_name("sweep_report.py")
        command = [sys.executable, str(sweep_script), "--prototype", args.prototype,
                  "--seeds", *(str(seed) for seed in (args.seeds or [1, 2, 3, 4, 5]))]
        if args.report_dir is not None:
            command += ["--report-dir", str(args.report_dir)]
        if args.nextpnr_options:
            command += ["--nextpnr-options", *args.nextpnr_options]
        if args.compare is not None:
            command += ["--compare", str(args.compare.resolve())]
        if args.jobs is not None:
            command += ["--jobs", str(args.jobs)]
        if args.promote is not None:
            command += ["--promote", args.promote]
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
