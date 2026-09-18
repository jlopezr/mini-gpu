#!/usr/bin/env python3
"""Ejecuta un programa en una FPGA real: resuelve el prototipo, comprueba (y si
hace falta sube) el bitstream correcto, carga el programa y lo ejecuta.

Reutiliza x.tests/backends/board.py para todo lo que habla con la placa: este
módulo no es un segundo sistema de programación FPGA, solo la composición de
esas piezas con resolución de prototipos."""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prototype import PrototypeResolutionError, find_repo_root, resolve_prototype
from tools.prototype_report import _capabilities

sys.path.insert(0, str(ROOT / "x.tests"))
from backends import board  # noqa: E402


# Reexportados desde backends.board, que es donde vive la lógica compartida
# con run_tests.py (x.tests no depende de tools/, así que la dirección de la
# dependencia solo puede ir de aquí hacia allá).
FTDI_VENDOR_ID = board.FTDI_VENDOR_ID
detect_port = board.detect_port


def load_monitor(prototype_dir: Path) -> ModuleType:
    path = prototype_dir / "monitor.py"
    if not path.exists():
        raise SystemExit(f"error: {prototype_dir.name} no tiene monitor.py")
    spec = importlib.util.spec_from_file_location(f"monitor_{prototype_dir.name}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"error: no se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_monitor_cli(prototype_dir: Path, port: str, *args: str) -> str:
    """Invoca `monitor.py <args>` como subproceso, igual que run-demo.ps1 /
    capture-frames.ps1: el CLI ya sabe formatear cada comando, no hay que
    reimplementar el protocolo aquí."""
    command = [sys.executable, str(prototype_dir / "monitor.py"), *args, "--port", port]
    completed = subprocess.run(command, cwd=str(prototype_dir), capture_output=True, text=True)
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise SystemExit(f"error: `monitor.py {' '.join(args)}` falló:\n{output}")
    print(output, end="" if output.endswith("\n") else "\n")
    return output


def assemble(root: Path, source: Path, verbose: bool) -> Path:
    binary = source.with_suffix(".bin")
    # `-I x.tests/inc` da acceso a la biblioteca de `.include` compartida. La
    # carpeta del propio .asm se mira siempre primero y antes que esta, asi que
    # un trozo local con el mismo nombre sigue ganando.
    command = [sys.executable, str(root / "1.isa" / "miniisa_asm.py"), str(source),
               "-o", str(binary), "-I", str(root / "x.tests" / "inc")]
    if verbose:
        print(f"$ {' '.join(command)}")
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise SystemExit(f"error: el ensamblado de {source} falló")
    return binary


_SEARCH_EXCLUDE = {".git", ".venv", "_build", "node_modules"}


def resolve_program(prototype_dir: Path, program: str, root: Path | None = None) -> Path:
    candidate = Path(program)
    if candidate.exists():
        return candidate.resolve()
    for base in (Path.cwd(), prototype_dir, prototype_dir / "examples"):
        for name in (program, f"{program}.asm", f"{program}.bin"):
            found = base / name
            if found.exists():
                return found.resolve()

    # Nombre suelto, sin ruta: como run-demo.ps1, busca en todo el repo antes
    # de rendirse (útil para programas de otra carpeta, ej. un caso de x.tests).
    if root is not None and "/" not in program and "\\" not in program:
        name = program if program.endswith((".asm", ".bin")) else f"{program}.asm"
        matches = sorted(
            p for p in root.rglob(name)
            if not any(part in _SEARCH_EXCLUDE for part in p.parts)
        )
        if len(matches) == 1:
            return matches[0].resolve()
        if len(matches) > 1:
            listed = "\n".join(str(p) for p in matches)
            raise SystemExit(f"error: hay varios programas llamados '{name}'. Indica una ruta:\n{listed}")

    raise SystemExit(f"error: no se encontró el programa '{program}' (probado en el directorio "
                     f"actual, {prototype_dir}, {prototype_dir / 'examples'}"
                     f"{f' y en todo {root}' if root is not None else ''})")


class Target:
    """Prototipo ya resuelto: carpeta, raíz del repo, monitor cargado y la
    identidad (versión/clock/capabilities) leída del RTL, si tiene cpu.v o
    gpu_sm.v/gpu_system.v + monitor.v con versión. Comparten esto
    board-info/board-upload/board-load/run-board."""

    def __init__(self, prototype_dir: Path, root: Path, monitor: ModuleType, capability: dict):
        self.prototype_dir = prototype_dir
        self.root = root
        self.monitor = monitor
        self.capability = capability


def resolve_target(prototype_value: str) -> Target:
    root = find_repo_root(Path.cwd())
    try:
        prototype_dir = resolve_prototype(prototype_value, root=root)
    except PrototypeResolutionError as exc:
        raise SystemExit(f"error: {exc}")
    print(f"Using prototype: {prototype_dir.name}")
    monitor = load_monitor(prototype_dir)
    capability = _capabilities(prototype_dir, root)
    return Target(prototype_dir, root, monitor, capability)


def check_identity(target: Target, port: str, serial_timeout: float) -> int:
    """Solo lee la versión del monitor; nunca sube nada. Para `board-info`."""
    try:
        actual = board.read_monitor_version(target.monitor, port, serial_timeout)
    except (board.BoardNotConnected, board.MonitorSilent) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    actual_text = ".".join(map(str, actual))
    if not target.capability:
        print(
            f"aviso: {target.prototype_dir.name} no tiene cpu.v/gpu_sm.v/"
            "gpu_system.v + monitor.v con versión; no se puede comparar "
            f"contra una versión esperada. Monitor actual: {actual_text}.",
            file=sys.stderr,
        )
        return 0
    expected = target.capability["monitor_version"]
    expected_text = ".".join(map(str, expected))
    if actual == expected:
        print(f"OK: monitor {actual_text} (versión {target.capability['version_name']}).")
        return 0
    print(
        f"MISMATCH: la placa responde {actual_text}; "
        f"{target.prototype_dir.name} espera {expected_text} "
        f"(versión {target.capability['version_name']}).",
        file=sys.stderr,
    )
    return 1


def ensure_uploaded(target: Target, port: str, serial_timeout: float,
                    policy, rebuild: bool) -> int:
    """Comprueba (y si hace falta y la política lo permite, sube) el
    bitstream correcto. Para `board-upload` y para el flujo por defecto de
    `run-board`."""
    if not target.capability:
        print(
            f"aviso: {target.prototype_dir.name} no tiene cpu.v/gpu_sm.v/"
            "gpu_system.v + monitor.v con versión; no se puede comprobar la "
            "identidad del bitstream automáticamente.",
            file=sys.stderr,
        )
        try:
            board.read_monitor_version(target.monitor, port, serial_timeout)
        except (board.BoardNotConnected, board.MonitorSilent) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    expected = target.capability["monitor_version"]
    version_name = target.capability["version_name"]
    backend_name = target.capability["backend"]
    # La version del monitor dice QUE DISEÑO hay en la placa, pero no si es el
    # ULTIMO BUILD de ese diseño: cambiar la LSU, el camino de memoria o la
    # lane no la mueve, asi que la identidad daba por bueno un bitstream viejo.
    # El sello de `board.upload` cierra ese hueco comparando fechas del lado
    # del anfitrion, que es el unico que puede saberlas.
    stale = board.bitstream_newer_than_upload(target.prototype_dir)
    if stale and not rebuild:
        print(f"el bitstream de {target.prototype_dir.name} es mas nuevo que el "
              "ultimo programado: subiendolo")

    if rebuild or stale:
        if rebuild:
            print(f"--rebuild: forzando `apio upload` en {target.prototype_dir}")
        try:
            board.upload(target.prototype_dir)
        except board.BitstreamMismatch as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        board.ensure_bitstream(
            target.monitor, port, serial_timeout, expected, target.prototype_dir,
            backend_name, version_name, policy,
        )
    except (board.BoardNotConnected, board.MonitorSilent, board.BitstreamMismatch) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def load_and_run(target: Target, program: str, port: str, no_run: bool, verbose: bool) -> int:
    """Ensambla si hace falta, carga y (salvo --no-run) ejecuta un programa.
    No comprueba el bitstream: quien llama decide si hace falta. Para
    `board-load` y para `run-board --program`."""
    prototype_dir, root = target.prototype_dir, target.root
    source = resolve_program(prototype_dir, program, root)
    binary = assemble(root, source, verbose) if source.suffix == ".asm" else source

    print(f"== cargando {binary.name} ({binary.stat().st_size} bytes) en 0x00000000")
    run_monitor_cli(prototype_dir, port, "reset")
    run_monitor_cli(prototype_dir, port, "write-block", "0", str(binary))

    if no_run:
        print("== cargado; la CPU sigue parada (--no-run)")
        return 0

    print("== arrancando")
    run_monitor_cli(prototype_dir, port, "run")
    time.sleep(0.3)
    status = run_monitor_cli(prototype_dir, port, "status")
    if "error=True" in status:
        print("!! la CPU se ha detenido con error", file=sys.stderr)
    if target.capability and "video" in target.capability.get("capabilities", ()):
        # Se pregunta SIEMPRE, corriendo o parado. Hubo aqui una excepcion para
        # la GPU --su puerto host rechazaba toda transaccion en marcha, asi que
        # preguntar abortaba el comando con un NACK que parecia un bitstream
        # malo-- que desaparece con la fase 3.4: las cuatro GPU atienden ahora
        # las LECTURAS de MMIO con el nucleo en marcha, igual que la CPU. Y es
        # justo cuando interesa mirar el underflow: en una demo que no para.
        video_status = run_monitor_cli(prototype_dir, port, "read-byte", "0x8000000c")
        if ":" in video_status and int(video_status.rsplit(":", 1)[1].strip(), 16) & 1:
            print("!! underflow de video marcado (pegajoso: puede venir de antes)", file=sys.stderr)
    return 0


def open_console(target: Target, port: str) -> int:
    """Deja una consola serie interactiva (`monitor.py console`). Solo la
    tienen los monitores con capacidad `serial`."""
    command = [sys.executable, str(target.prototype_dir / "monitor.py"), "console", "--port", port]
    try:
        completed = subprocess.run(command, cwd=str(target.prototype_dir))
    except KeyboardInterrupt:
        return 0
    if completed.returncode == 2:
        print(
            f"aviso: {target.prototype_dir.name} no tiene comando `console` "
            "(solo lo tienen los monitores con capacidad `serial`). "
            "Usa `monitor.py status`/`read-register` a mano.",
            file=sys.stderr,
        )
    return completed.returncode


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--prototype", required=True)
    parser.add_argument("--port", default=None, help="por defecto, detecta el primer adaptador FTDI conectado")
    parser.add_argument("--serial-timeout", type=float, default=1.0)


def _resolve_port(args: argparse.Namespace) -> str:
    return args.port if args.port is not None else detect_port()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_common_args(parser)
    parser.add_argument("--program", help="ruta o nombre de un .asm/.bin; se omite para solo comprobar identidad")
    parser.add_argument("--rebuild", action="store_true", help="fuerza `apio upload` aunque la identidad ya coincida")
    parser.add_argument("--upload", dest="upload", action="store_true", default=None)
    parser.add_argument("--no-upload", dest="upload", action="store_false")
    parser.add_argument("-y", "--yes", action="store_true", help="autoriza la carga del bitstream sin preguntar")
    parser.add_argument("--reset", action="store_true", help="solo resetea la CPU y sale")
    parser.add_argument("--no-run", action="store_true", help="carga el programa pero no lo arranca")
    parser.add_argument("--interactive", action="store_true", help="deja una consola serie interactiva al terminar")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    port = _resolve_port(args)

    target = resolve_target(args.prototype)

    policy = board.UploadPolicy(allowed=args.upload is not False, assume_yes=args.yes)
    code = ensure_uploaded(target, port, args.serial_timeout, policy, args.rebuild)
    if code != 0:
        return code

    if args.reset:
        run_monitor_cli(target.prototype_dir, port, "reset")
        return 0

    if args.program:
        code = load_and_run(target, args.program, port, args.no_run, args.verbose)
        if code != 0:
            return code

    if args.interactive:
        open_console(target, port)

    return 0


def main_info(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comprueba la identidad del monitor en placa, sin subir nada.")
    _add_common_args(parser)
    args = parser.parse_args(argv)
    port = _resolve_port(args)
    target = resolve_target(args.prototype)
    return check_identity(target, port, args.serial_timeout)


def main_upload(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comprueba (y si hace falta sube) el bitstream correcto.")
    _add_common_args(parser)
    parser.add_argument("--rebuild", action="store_true", help="fuerza `apio upload` aunque la identidad ya coincida")
    parser.add_argument("--no-upload", dest="upload", action="store_false", default=None,
                        help="falla en vez de subir si el bitstream no coincide")
    parser.add_argument("-y", "--yes", action="store_true", help="autoriza la carga sin preguntar")
    args = parser.parse_args(argv)
    port = _resolve_port(args)
    target = resolve_target(args.prototype)
    policy = board.UploadPolicy(allowed=args.upload is not False, assume_yes=args.yes)
    return ensure_uploaded(target, port, args.serial_timeout, policy, args.rebuild)


def main_load(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Carga (y por defecto ejecuta) un programa; no comprueba el bitstream."
    )
    _add_common_args(parser)
    parser.add_argument("--program", required=True, help="ruta o nombre de un .asm/.bin")
    parser.add_argument("--no-run", action="store_true", help="carga el programa pero no lo arranca")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    port = _resolve_port(args)
    target = resolve_target(args.prototype)
    return load_and_run(target, args.program, port, args.no_run, args.verbose)


def main_test(argv: list[str] | None = None) -> int:
    """Resuelve backend y versión de x.tests/run_tests.py a partir del RTL
    (igual que board-info/board-upload) y reenvía el resto de argumentos.
    Evita tener que saber a mano si un prototipo es cpu-fpga o gpu-fpga."""
    parser = argparse.ArgumentParser(
        description="Ejecuta x.tests/run_tests.py contra placa real, "
                    "infiriendo --backend/--version del prototipo.",
        epilog="El resto de opciones (TEST_JSON, --trace, -y, --measure...) "
              "se reenvían tal cual a run_tests.py.",
    )
    parser.add_argument("-p", "--prototype", required=True)
    parser.add_argument("--port", default=None, help="por defecto, detecta el primer adaptador FTDI conectado")
    args, extra = parser.parse_known_args(argv)

    port = args.port if args.port is not None else detect_port()
    target = resolve_target(args.prototype)
    if not target.capability:
        raise SystemExit(
            f"error: {target.prototype_dir.name} no tiene cpu.v/gpu_sm.v/"
            "gpu_system.v + monitor.v con versión; no se puede inferir "
            "--backend/--version. Usa x.tests/run_tests.py directamente."
        )

    backend = f"{target.capability['backend']}-fpga"
    version = target.capability["version_name"]
    command = [
        sys.executable, str(target.root / "x.tests" / "run_tests.py"),
        "--backend", backend, "--version", version, "--port", port,
        *extra,
    ]
    print(f"$ {' '.join(command)}")
    return subprocess.run(command).returncode


if __name__ == "__main__":
    raise SystemExit(main())
