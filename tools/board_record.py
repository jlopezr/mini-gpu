"""Registro de lo que se probo EN PLACA, con hashes de lo que se uso.

Una tabla de builds dice si un bitstream cerro timing, pero no si alguien lo llevo
a la placa ni que paso. Este modulo cierra ese hueco en dos mitades:

  * `record_upload` anota, cada vez que se programa la placa, el SHA-256 del
    bitstream y de donde salio. La placa es UNA para todos los worktrees, asi que
    el estado vive en el usuario (`~/.mini-gpu/board-state.json`) y no en una
    carpeta de prototipo.
  * `build_record` / `write_record` lo cruzan, al terminar una suite, con el
    resultado de cada caso y lo guardan junto al build al que pertenece ese
    bitstream (por hash, no por fecha): `reports/<build>/board-tests.json`.

Que NO prueba, para no venderlo de mas: el hash dice que bitstream SE PROGRAMO
desde estas herramientas. Si alguien reprograma la placa por fuera, el registro no
se entera; lo acota la version del monitor, leida antes y despues de la suite. Una
identidad dentro del propio bitstream (fase 2) lo haria fehaciente.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

BOARD_TESTS_JSON = "board-tests.json"
STATE_FILE = Path(os.environ.get("MINI_GPU_STATE_DIR", Path.home() / ".mini-gpu")) / "board-state.json"

_IGNORED_PARTS = {"__pycache__", ".git"}
_folder_cache: dict[Path, str] = {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def folder_sha256(folder: Path) -> str:
    """Hash del contenido de una carpeta (nombres relativos y bytes, en orden).

    Es el del CASO: `test.json`, el programa y lo que lleve al lado. Si cambia el
    programa o lo esperado, cambia el hash, y el registro lo delata."""
    folder = Path(folder).resolve()
    cached = _folder_cache.get(folder)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()
                       and not (set(p.relative_to(folder).parts) & _IGNORED_PARTS)
                       and p.suffix != ".pyc"):
        digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    _folder_cache[folder] = digest.hexdigest()
    return _folder_cache[folder]


# ---- estado de la placa ----------------------------------------------------

def record_upload(project: Path, bitstream: Path) -> None:
    """Anota que bitstream se acaba de programar. Nunca rompe la subida."""
    try:
        bitstream = Path(bitstream).resolve()
        state = {
            "bitstream_sha256": sha256_file(bitstream),
            "bitstream_path": str(bitstream),
            "bitstream_size": bitstream.stat().st_size,
            "prototype": Path(project).name,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "host": socket.gethostname(),
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"aviso: no se pudo anotar la subida ({error})")


def last_upload() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---- identidad del build ---------------------------------------------------

def find_build(project: Path, bitstream_sha256: str, size: int | None = None) -> Path | None:
    """Carpeta de `reports/` cuyo `hardware.bit` tiene ese hash, la mas nueva."""
    reports = Path(project) / "reports"
    if not reports.is_dir():
        return None
    for folder in sorted((p for p in reports.iterdir() if p.is_dir()), reverse=True):
        bit = folder / "hardware.bit"
        try:
            if not bit.is_file() or (size is not None and bit.stat().st_size != size):
                continue
            if sha256_file(bit) == bitstream_sha256:
                return folder
        except OSError:
            continue
    return None


def _relevant(name: str) -> bool:
    suffix = Path(name).suffix
    return (name == "apio.ini" or suffix in {".v", ".sv", ".vh", ".lpf", ".hex"}) \
        and not Path(name).name.endswith("_tb.v")


def _lf(data: bytes) -> str:
    """SHA-256 con saltos de linea LF: CRLF/LF/mezcla dan el mismo RTL."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def normalized_source_hashes(project: Path) -> dict[str, str]:
    """Hashes (saltos de linea LF) de las fuentes sintetizables de un prototipo."""
    from tools.build_report import synthesizable_source_hashes
    project = Path(project)
    return {name.replace("\\", "/"): _lf((project / name).read_bytes())
            for name in synthesizable_source_hashes(project) if _relevant(name)}


def sources_match(project: Path, build_folder: Path | None) -> bool | None:
    """Si las fuentes sintetizables de AHORA son las de ese build.

    True/False solo cuando se puede decir en serio: el build guarda hashes con
    saltos de linea LF (`source_sha256_lf`) o sus fuentes (`sources.zip`). Un
    build antiguo solo tiene el hash de los bytes, y un checkout con autocrlf (otro
    worktree) los cambia sin tocar el RTL: ahi un desacuerdo no prueba nada y se
    devuelve None ("no verificable") en vez de dar una alarma falsa."""
    if build_folder is None:
        return None
    try:
        current = normalized_source_hashes(project)
        metadata = json.loads((build_folder / "metadata.json").read_text(encoding="utf-8"))
        archive = build_folder / "sources.zip"
        if metadata.get("source_sha256_lf"):
            archived = {k.replace("\\", "/"): v for k, v in metadata["source_sha256_lf"].items()
                        if _relevant(k)}
        elif archive.is_file():
            with zipfile.ZipFile(archive) as bundle:
                archived = {name.replace("\\", "/"): _lf(bundle.read(name))
                            for name in bundle.namelist() if _relevant(name)}
        else:
            raw = {k.replace("\\", "/"): v for k, v in metadata.get("source_sha256", {}).items()
                   if _relevant(k)}
            from tools.build_report import synthesizable_source_hashes
            now = {k.replace("\\", "/"): v for k, v in synthesizable_source_hashes(Path(project)).items()
                   if _relevant(k)}
            return True if raw == now else None
        return archived == current
    except (OSError, json.JSONDecodeError, KeyError, zipfile.BadZipFile):
        return None

def git_info(root: Path) -> dict:
    git = shutil.which("git")
    if git is None:
        return {"commit": None, "dirty_files": None}
    def run(*args):
        return subprocess.run([git, *args], cwd=root, capture_output=True, text=True, check=False)
    try:
        commit = run("rev-parse", "HEAD").stdout.strip() or None
        dirty = [line[3:] for line in run("status", "--porcelain").stdout.splitlines()]
    except OSError:
        return {"commit": None, "dirty_files": None}
    return {"commit": commit, "dirty_files": dirty}


# ---- el registro -----------------------------------------------------------

def build_record(*, project: Path, root: Path, port: str, family: list[str],
                 arguments: list[str], full_suite: bool, results: list[dict],
                 skipped: int, monitor_before, monitor_after, unprepared: int = 0) -> dict:
    upload = last_upload()
    sha = upload["bitstream_sha256"] if upload else None
    size = upload.get("bitstream_size") if upload else None
    provenance = "subido con las herramientas" if upload else "desconocida (no hay subida anotada)"
    if upload and upload.get("prototype") != Path(project).name:
        provenance = (f"la ultima subida fue de otro prototipo ({upload.get('prototype')}); "
                      "la placa puede llevar otro bitstream")
    build = find_build(project, sha, size) if sha else None
    counts = {"pass": 0, "fail": 0, "error": 0}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "prototype": Path(project).name,
        "port": port,
        "families": family,
        "bitstream": {
            "sha256": sha,
            "uploaded_at": upload.get("uploaded_at") if upload else None,
            "uploaded_from": upload.get("bitstream_path") if upload else None,
            "provenance": provenance,
            "build_folder": build.name if build else None,
            "sources_match_build": sources_match(project, build),
        },
        "monitor_version": {
            "before": ".".join(map(str, monitor_before)) if monitor_before else None,
            "after": ".".join(map(str, monitor_after)) if monitor_after else None,
        },
        "git": git_info(root),
        "run_tests_sha256": (sha256_file(root / "t.tests" / "run_tests.py")
                             if (root / "t.tests" / "run_tests.py").is_file() else None),
        "selection": {"full_suite": full_suite, "arguments": arguments},
        # `unprepared`: casos que ni llegaron a la placa (no compilaron, falta un
        # submodulo...). Cuentan como NO superados: un verde sin ellos mentiria.
        "totals": {**counts, "skipped": skipped, "unprepared": unprepared,
                   "executed": len(results)},
        "results": results,
    }


def write_record(project: Path, record: dict) -> Path:
    """Junto al build al que pertenece el bitstream; si no hay, en una carpeta propia."""
    project = Path(project)
    folder_name = record["bitstream"]["build_folder"]
    if folder_name:
        path = project / "reports" / folder_name / BOARD_TESTS_JSON
    else:
        stamp = record["timestamp"].replace(":", "").replace("-", "").replace("T", "-")
        path = project / "reports" / f"{stamp}-board-tests-sin-build" / BOARD_TESTS_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = []
    if path.is_file():
        try:
            runs = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
        except (OSError, json.JSONDecodeError):
            runs = []
    runs.append(record)
    path.write_text(json.dumps({"runs": runs}, indent=2) + "\n", encoding="utf-8")
    return path


def summary_line(record: dict) -> str:
    totals = record["totals"]
    ok = totals["pass"]
    bad = totals["fail"] + totals["error"]
    not_run = totals.get("unprepared", 0)
    scope = "completa" if record["selection"]["full_suite"] else "parcial"
    match = record["bitstream"]["sources_match_build"]
    tail = "" if match is not False else "  [!] las fuentes actuales NO son las de ese build"
    return (f"{record['timestamp']}  {'+'.join(record['families'])}  {ok} PASS / {bad} FAIL"
            f" / {not_run} sin preparar / {totals['skipped']} omitidos  (suite {scope}){tail}")


def board_status(build_folder: Path) -> str:
    """Texto corto para las tablas de builds: que se probo en placa con ESE bitstream."""
    try:
        runs = json.loads((Path(build_folder) / BOARD_TESTS_JSON).read_text(encoding="utf-8")).get("runs", [])
    except (OSError, json.JSONDecodeError):
        return "sin probar"
    if not runs:
        return "sin probar"
    full = [r for r in runs if r["selection"]["full_suite"]]
    last = (full or runs)[-1]
    totals = last["totals"]
    bad = totals["fail"] + totals["error"] + totals.get("unprepared", 0)
    scope = "" if last["selection"]["full_suite"] else " parcial"
    return f"{totals['pass']}/{totals['pass'] + bad}{scope} {last['timestamp'][:10]}"
