"""Comprobación de la placa y carga del bitstream que requiere cada backend.

Separa dos situaciones que se arreglan de forma distinta:

- La placa no responde: no hay nada que subir, es un error seco.
- La placa responde con otro monitor: se puede reconstruir y programar.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


# VID de FTDI; el chip USB-serie de la ULX3S (y de casi cualquier placa de
# desarrollo FPGA) es un FT2232/FT232 de FTDI, así que detectarlo por VID es
# fiable sin tener que mantener una lista de descripciones por SO.
FTDI_VENDOR_ID = 0x0403


def detect_port() -> str:
    """Busca el primer FTDI conectado. En Mac/Linux no hay "COM3" que valga
    por defecto, así que sin --port explícito hay que adivinar el puerto.
    Comparte esta lógica run_tests.py y tools/run_board.py."""
    from serial.tools import list_ports

    candidates = [port for port in list_ports.comports() if port.vid == FTDI_VENDOR_ID]
    if not candidates:
        all_ports = ", ".join(p.device for p in list_ports.comports()) or "ninguno"
        raise SystemExit(
            "error: no se encontró ningún adaptador FTDI conectado. "
            f"Puertos serie disponibles: {all_ports}. Indica --port a mano."
        )
    if len(candidates) > 1:
        listed = ", ".join(f"{p.device} ({p.description})" for p in candidates)
        raise SystemExit(
            f"error: hay varios adaptadores FTDI conectados: {listed}. "
            "Indica --port a mano."
        )
    port = candidates[0]
    print(f"Detected port: {port.device} ({port.description})")
    return port.device


def region_incompatibility(case: dict, regions: tuple) -> str | None:
    """Comprueba los rangos de un caso contra el mapa real de una versión.

    Una lista de regiones, y no un tamaño, porque `ebr` tiene dos bancos
    separados por un hueco que el bus rechaza: un límite escalar no puede
    expresarlo. Cada rango debe caber entero dentro de una sola región.
    """
    ranges = [("programa", 0, len(case["program"]))]
    ranges += [("memoria inicial", address, len(data))
               for address, data in case["initial_memory"]]
    ranges += [("dump esperado", address, size)
               for address, size in case["expected"]["memory"]]
    for name, address, size in ranges:
        if not any(start <= address and address + size <= end
                   for start, end in regions):
            available = ", ".join(f"0x{start:x}-0x{end - 1:x}"
                                  for start, end in regions)
            return (f"{name} fuera del mapa de memoria: 0x{address:x} + {size} "
                    f"bytes; disponible: {available}")
    return None


class BoardNotConnected(RuntimeError):
    """No se puede ni abrir el puerto: no hay placa con la que hablar."""


class MonitorSilent(RuntimeError):
    """El puerto abre pero el monitor no contesta.

    El chip USB-serie de la placa enumera siempre, tenga o no bitstream la FPGA,
    así que esto suele significar que no hay ninguno cargado. Se arregla
    igual que una versión equivocada: cargando el que toca.
    """


class BitstreamMismatch(RuntimeError):
    """La placa responde, pero con una versión de monitor distinta."""


@dataclass(frozen=True)
class UploadPolicy:
    """Qué puede hacer el runner si el bitstream no es el que toca."""

    allowed: bool = True      # --no-upload lo desactiva
    assume_yes: bool = False  # --yes evita la confirmación

    def confirm(self, question: str) -> bool:
        if self.assume_yes:
            return True
        if not sys.stdin.isatty():
            # Sin terminal no hay a quién preguntar: mejor fallar que colgarse.
            raise BitstreamMismatch(
                f"{question}\nNo hay terminal interactiva para confirmar; "
                "repite con --yes para autorizar la carga, o con --no-upload "
                "para exigir que la placa ya tenga el bitstream correcto."
            )
        answer = input(f"{question} [s/N] ").strip().lower()
        return answer in ("s", "si", "sí", "y", "yes")


def _open(monitor: ModuleType, port: str, serial_timeout: float):
    serial = monitor.serial
    try:
        return serial.Serial(
            port=port,
            baudrate=monitor.BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=serial_timeout,
            write_timeout=serial_timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
    except Exception as error:  # serial.SerialException y afines
        raise BoardNotConnected(
            f"No se puede abrir {port}: {error}.\nComprueba que la placa está "
            "conectada y que ningún otro programa tiene el puerto abierto."
        ) from error


def read_monitor_version(monitor: ModuleType, port: str,
                         serial_timeout: float) -> tuple[int, int]:
    """Versión del monitor que hay ahora mismo en la placa."""
    with _open(monitor, port, serial_timeout) as connection:
        try:
            version = monitor.MonitorClient(connection).get_version()
        except Exception as error:
            raise MonitorSilent(
                f"La placa en {port} no responde a GET_VERSION: {error}.\n"
                "Probablemente la FPGA no tiene ningún bitstream con monitor."
            ) from error
    return (version.major, version.minor)


def _find_fujprog() -> str:
    """Localiza `fujprog` (el programador de la ULX3S) en la instalación de
    oss-cad-suite que gestiona apio, sin pasar por `apio upload`/SCons."""
    filename = "fujprog.exe" if sys.platform == "win32" else "fujprog"
    candidate = Path.home() / ".apio" / "packages" / "oss-cad-suite" / "bin" / filename
    return str(candidate) if candidate.exists() else filename


def _is_ulx3s(project: Path) -> bool:
    apio_ini = project / "apio.ini"
    return apio_ini.exists() and "ulx3s" in apio_ini.read_text(encoding="utf-8", errors="replace")


def _fresh_bitstream(project: Path) -> Path | None:
    """`_build/default/hardware.bit` si es más reciente que todo el RTL,
    constraints y `apio.ini` del proyecto; si no, None.

    Evita relanzar el build (y con él todo `nextpnr`) cuando `build` ya
    dejó un bitstream válido para las fuentes actuales: `apio build` añade
    `--verbose-pnr` para su propio informe, lo que cambia la firma del
    comando que ve SCons frente a otros lanzadores, que podrían repetir
    síntesis+PNR enteros aunque nada haya cambiado.
    """
    if not _is_ulx3s(project):
        return None
    from tools.build_report import bitstream_is_current, default_env

    bitstream = project / "_build" / default_env(project) / "hardware.bit"
    return bitstream if bitstream_is_current(project) else None


def _upload_stamp(project: Path) -> Path:
    """Fichero donde se anota qué bitstream se programó la última vez."""
    return project / "_build" / "default" / ".uploaded"


def _mark_uploaded(project: Path) -> None:
    """Anota la fecha del bitstream recién programado.

    La versión del monitor dice QUÉ DISEÑO hay en la placa, pero no si es el
    último build de ese diseño: cambiar la LSU, el camino de memoria o la lane
    no mueve esa versión, así que la comprobación de identidad da por bueno un
    bitstream viejo. Ese fallo costó una sesión entera de depuración contra una
    placa que llevaba el bitstream anterior.

    La fecha no puede preguntarse a la FPGA —no sabe cuándo la programaron—,
    así que se anota aquí, del lado del anfitrión.
    """
    bitstream = project / "_build" / "default" / "hardware.bit"
    if not bitstream.exists():
        return
    stamp = _upload_stamp(project)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(str(bitstream.stat().st_mtime_ns), encoding="utf-8")


def bitstream_newer_than_upload(project: Path) -> bool:
    """El bitstream del proyecto es más nuevo que el último que se programó.

    Estado LOCAL, con dos límites que conviene conocer: si se graba desde otro
    ordenador el sello de éste miente, y si se programa a SRAM y se apaga la
    placa el bitstream se pierde pero el sello se queda. Lo segundo sí lo caza
    la comprobación de versión del monitor, que dejaría de responder; por eso
    hacen falta las dos y no uno sola.
    """
    bitstream = project / "_build" / "default" / "hardware.bit"
    if not bitstream.exists():
        return False
    stamp = _upload_stamp(project)
    if not stamp.exists():
        # Nunca se subió desde aquí: no se puede afirmar que la placa lo tenga.
        return True
    try:
        uploaded_at = int(stamp.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return True
    return bitstream.stat().st_mtime_ns > uploaded_at


def _program_bitstream(project: Path, bitstream: Path, mark: bool = True) -> None:
    """Program an already validated bitstream without rebuilding it.

    `mark=False` es para un bitstream que NO es el de `_build/default` (uno
    archivado en `reports/`): no se sella como subido, y se borra el sello viejo,
    para que la siguiente subida normal vuelva a programar el del proyecto."""
    print(f"--- `fujprog` directo con {bitstream} ---", flush=True)
    try:
        completed = subprocess.run(
            [_find_fujprog(), "-l", "2", str(bitstream)], cwd=project)
    except FileNotFoundError as error:
        raise BitstreamMismatch(
            "No se encuentra `fujprog`; instálalo o carga el bitstream "
            f"a mano desde {project}."
        ) from error
    print("--- fin de `fujprog` ---", flush=True)
    if completed.returncode != 0:
        raise BitstreamMismatch(
            f"`fujprog` falló en {project} con código "
            f"{completed.returncode}; revisa su salida más arriba."
        )
    time.sleep(1.5)
    if mark:
        _mark_uploaded(project)
    else:
        _upload_stamp(project).unlink(missing_ok=True)


def upload_archived(project: Path, bitstream: Path) -> None:
    """Programa un bitstream ya construido y archivado (p. ej. el de un build
    viejo de `reports/`), sin tocar `_build/default`."""
    _program_bitstream(project, bitstream, mark=False)


def upload(project: Path) -> None:
    """Build when needed, then program the project's current bitstream.

    The build uses the common tracked path, so automatic test-triggered
    synthesis appears in ``build-list`` and archives its timing report.
    """
    bitstream = _fresh_bitstream(project)
    if bitstream is not None:
        _program_bitstream(project, bitstream)
        return

    repository = Path(__file__).resolve().parents[2]
    print(f"--- build registrado de {project} "
          f"(puede tardar varios minutos) ---", flush=True)
    try:
        completed = subprocess.run([
            sys.executable, "-m", "tools.build_runner", "build",
            "--prototype", str(project), "--label", "auto-upload",
        ], cwd=repository)
    except FileNotFoundError as error:
        raise BitstreamMismatch(
            "No se pudo ejecutar el build común; comprueba el entorno Python "
            f"y las herramientas de síntesis para {project}."
        ) from error
    print("--- fin del build registrado ---", flush=True)
    if completed.returncode != 0:
        raise BitstreamMismatch(
            f"El build de {project} falló con código "
            f"{completed.returncode}; revisa su salida más arriba."
        )
    bitstream = _fresh_bitstream(project)
    if bitstream is None:
        raise BitstreamMismatch(
            f"El build de {project} terminó sin dejar un bitstream actualizado."
        )
    _program_bitstream(project, bitstream)


def ensure_bitstream(monitor: ModuleType, port: str, serial_timeout: float,
                     expected: tuple[int, int], project: Path,
                     backend: str, version_name: str,
                     policy: UploadPolicy) -> None:
    """Deja la placa con el bitstream que este backend necesita.

    Sube el bitstream solo si la placa responde con otra versión, la política lo
    permite y el usuario lo confirma. Después vuelve a preguntar la versión: que
    El build y la programación pueden terminar sin que la placa quede con el
    monitor esperado, por eso se vuelve a comprobar después.
    """
    expected_text = ".".join(map(str, expected))
    try:
        actual = read_monitor_version(monitor, port, serial_timeout)
    except MonitorSilent as error:
        # Placa presente pero sin programar: se arregla cargando el bitstream.
        problem = (
            f"{error}\n"
            f"--backend {backend} --version {version_name} requiere "
            f"monitor {expected_text}."
        )
    else:
        if actual == expected:
            return
        actual_text = ".".join(map(str, actual))
        problem = (
            f"La placa en {port} responde con monitor {actual_text}, pero "
            f"--backend {backend} --version {version_name} requiere "
            f"{expected_text}."
        )
    if not policy.allowed:
        raise BitstreamMismatch(
            f"{problem}\nCarga el bitstream de {project} o quita --no-upload."
        )
    if not policy.confirm(f"{problem}\n¿Cargar el bitstream de {project}?"):
        raise BitstreamMismatch(f"{problem}\nCarga cancelada.")

    upload(project)

    try:
        actual = read_monitor_version(monitor, port, serial_timeout)
    except MonitorSilent as error:
        raise BitstreamMismatch(
            f"Tras reconstruir y programar, la placa sigue sin responder: {error} "
            f"Revisa que {project} sea el proyecto correcto."
        ) from error
    if actual != expected:
        actual_text = ".".join(map(str, actual))
        raise BitstreamMismatch(
            f"Tras reconstruir y programar, la placa sigue respondiendo con monitor "
            f"{actual_text} en vez de {expected_text}. Revisa que {project} sea "
            "el proyecto correcto y que la carga llegara a la placa."
        )
    print(f"Bitstream correcto: monitor {expected_text}.")
