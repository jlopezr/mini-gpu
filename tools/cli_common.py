"""Opciones de línea de órdenes compartidas por las herramientas.

Una sola definición por opción, para que el nombre, la forma corta y el valor por defecto no
diverjan entre herramientas. Convenciones:

* `-p/--prototype`: texto (número o nombre de carpeta); lo resuelve `tools/prototype.py`.
  `prototype_number()` lo reduce al número cuando la herramienta necesita uno.
* `-y/--yes`: no preguntar.
* `-o/--output`: siempre un fichero. Una carpeta es `--output-dir`.
* `--json`: booleano; escribe JSON por stdout. Un fichero JSON es `--output-json`.
* `-j/--jobs`: trabajos en paralelo; 0 = automático.
* `-v/--verbose` y `-q/--quiet`.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_SERIAL_TIMEOUT = 1.0
FAMILIES = ("cpu", "gpu", "all")
TOOLCHAINS = ("apio", "diamond")


def add_prototype(parser: argparse.ArgumentParser, *, required: bool = False,
                  repeatable: bool = False, help: str | None = None) -> None:
    parser.add_argument("-p", "--prototype", required=required,
                        action="append" if repeatable else "store",
                        help=help or "prototipo (número o nombre de carpeta)")


def add_port(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", default=None,
                        help="puerto serie; por defecto, detecta el primer adaptador FTDI conectado")


def add_serial_timeout(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--serial-timeout", type=float, default=DEFAULT_SERIAL_TIMEOUT,
                        help="segundos de espera del puerto serie (por defecto %(default)s)")


def add_yes(parser: argparse.ArgumentParser, help: str = "no preguntar") -> None:
    parser.add_argument("-y", "--yes", action="store_true", help=help)


def add_output(parser: argparse.ArgumentParser, *, default: Path | None = None,
               help: str = "fichero de salida") -> None:
    parser.add_argument("-o", "--output", type=Path, default=default, help=help)


def add_output_dir(parser: argparse.ArgumentParser, *, default: Path | None = None,
                   help: str = "carpeta de salida") -> None:
    parser.add_argument("--output-dir", type=Path, default=default, help=help)


def add_json(parser: argparse.ArgumentParser, help: str = "salida en JSON por stdout") -> None:
    parser.add_argument("--json", action="store_true", help=help)


def add_verbosity(parser: argparse.ArgumentParser, *, quiet: bool = False) -> None:
    parser.add_argument("-v", "--verbose", action="store_true")
    if quiet:
        parser.add_argument("-q", "--quiet", action="store_true")


def add_jobs(parser: argparse.ArgumentParser, *, default: int = 0, help: str | None = None) -> None:
    parser.add_argument("-j", "--jobs", type=int, default=default, metavar="N",
                        help=help or "trabajos en paralelo (0 = automático)")


def add_family(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--family", choices=FAMILIES, default="all",
                        help="familia de prototipos (por defecto %(default)s)")


def add_bitstream(parser, *, group=None, repeatable: bool = False, required: bool = False,
                  type=None, metavar: str = "RUTA", help: str | None = None) -> None:
    """`-b/--bitstream`: un `hardware.bit` archivado, o la carpeta de `reports/` que lo contiene."""
    (group or parser).add_argument(
        "-b", "--bitstream", metavar=metavar, type=type, required=required,
        action="append" if repeatable else "store",
        help=help or "programa ESTE bitstream archivado (un hardware.bit o su carpeta de reports/) "
                     "en lugar del de _build/default")


def add_toolchain(parser, *, group=None, repeatable: bool = False, help: str | None = None) -> None:
    """`-t/--toolchain`: el último build archivado de esa herramienta cuyas fuentes son las actuales."""
    (group or parser).add_argument(
        "-t", "--toolchain", choices=TOOLCHAINS, action="append" if repeatable else "store",
        help=help or "programa el último build archivado de esa herramienta cuyas fuentes sean "
                     "las actuales (ver `board_record.find_latest_build`)")


def add_archived_build(parser, **kwargs) -> None:
    """`-b` y `-t` a la vez, excluyentes entre sí: la forma habitual de elegir qué se programa."""
    group = parser.add_mutually_exclusive_group()
    add_bitstream(parser, group=group, help=kwargs.get("bitstream_help"))
    add_toolchain(parser, group=group, help=kwargs.get("toolchain_help"))


def prototype_number(text: str) -> int:
    """Número de un prototipo dado como número, nombre de carpeta o ruta."""
    from tools.prototype import PrototypeResolutionError, resolve_prototype
    try:
        folder = resolve_prototype(text)
    except PrototypeResolutionError as error:
        raise argparse.ArgumentTypeError(str(error)) from None
    match = re.match(r"(\d+)", Path(folder).name)
    if match is None:
        raise argparse.ArgumentTypeError(f"{text!r}: la carpeta no empieza por un número")
    return int(match.group(1))
