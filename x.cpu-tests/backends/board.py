"""Comprobación de la placa y carga del bitstream que requiere cada backend.

Separa dos situaciones que se arreglan de forma distinta:

- La placa no responde: no hay nada que subir, es un error seco.
- La placa responde con otro monitor: se puede resolver con `apio upload`.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


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
            f"No se puede abrir {port}: {error}. Comprueba que la placa está "
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
                f"La placa en {port} no responde a GET_VERSION: {error}. "
                "Probablemente la FPGA no tiene ningún bitstream con monitor."
            ) from error
    return (version.major, version.minor)


def upload(project: Path) -> None:
    """Ejecuta `apio upload` en el directorio del proyecto."""
    print(f"Cargando el bitstream de {project.name} con `apio upload`...")
    try:
        completed = subprocess.run(
            ["apio", "upload"], cwd=project, text=True, capture_output=True,
        )
    except FileNotFoundError as error:
        raise BitstreamMismatch(
            "No se encuentra `apio` en el PATH; instálalo o carga el bitstream "
            f"a mano desde {project}."
        ) from error
    if completed.returncode != 0:
        raise BitstreamMismatch(
            f"`apio upload` falló en {project} con código "
            f"{completed.returncode}:\n{completed.stderr.strip()}"
        )


def ensure_bitstream(monitor: ModuleType, port: str, serial_timeout: float,
                     expected: tuple[int, int], project: Path,
                     backend: str, version_name: str,
                     policy: UploadPolicy) -> None:
    """Deja la placa con el bitstream que este backend necesita.

    Sube el bitstream solo si la placa responde con otra versión, la política lo
    permite y el usuario lo confirma. Después vuelve a preguntar la versión: que
    `apio upload` termine bien no garantiza que la placa quedara programada.
    """
    expected_text = ".".join(map(str, expected))
    try:
        actual = read_monitor_version(monitor, port, serial_timeout)
    except MonitorSilent as error:
        # Placa presente pero sin programar: se arregla cargando el bitstream.
        problem = (
            f"{error} --backend {backend} --version {version_name} requiere "
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
            f"{problem} Carga el bitstream de {project} o quita --no-upload."
        )
    if not policy.confirm(f"{problem}\n¿Cargar el bitstream de {project}?"):
        raise BitstreamMismatch(f"{problem} Carga cancelada.")

    upload(project)

    try:
        actual = read_monitor_version(monitor, port, serial_timeout)
    except MonitorSilent as error:
        raise BitstreamMismatch(
            f"Tras `apio upload` la placa sigue sin responder: {error} "
            f"Revisa que {project} sea el proyecto correcto."
        ) from error
    if actual != expected:
        actual_text = ".".join(map(str, actual))
        raise BitstreamMismatch(
            f"Tras `apio upload` la placa sigue respondiendo con monitor "
            f"{actual_text} en vez de {expected_text}. Revisa que {project} sea "
            "el proyecto correcto y que la carga llegara a la placa."
        )
    print(f"Bitstream correcto: monitor {expected_text}.")
