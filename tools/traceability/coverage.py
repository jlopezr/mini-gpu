"""Cobertura de marcado: qué ficheros descubiertos no declaran ninguna identidad."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .model import Model


@dataclass(frozen=True)
class FileCoverage:
    path: Path
    identities: int
    lines: int
    digest: str = ""


def file_coverage(model: Model) -> list[FileCoverage]:
    """Un FileCoverage por Resource, con las identidades declaradas en él."""
    declared: dict[Path, int] = {}
    for identity in model.identities:
        path = identity.location.path.resolve()
        declared[path] = declared.get(path, 0) + 1
    result = []
    for resource in model.resources:
        path = resource.path.resolve()
        lines, digest = _content(path)
        result.append(FileCoverage(path, declared.get(path, 0), lines, digest))
    return sorted(result, key=lambda item: _natural(item.path))


def _natural(path: Path) -> list[tuple[int, int, str]]:
    """Orden con los números como números: `6.x` antes que `10.x`."""
    key = []
    for part in path.parts:
        for chunk in re.split(r"(\d+)", part):
            key.append((0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk))
    return key


def unique_untraced(items: list[FileCoverage]) -> tuple[list[FileCoverage], dict[Path, list[Path]]]:
    """Sin marcar y sin copia previa: un representante por contenido idéntico.

    Un fichero sin identidades se omite si otro con el mismo contenido ya está
    marcado o aparece antes por ruta. Devuelve los representantes y, para cada
    uno, las rutas de sus copias.
    """
    by_digest: dict[str, list[FileCoverage]] = {}
    for item in items:
        if item.digest:
            by_digest.setdefault(item.digest, []).append(item)
    kept, copies = [], {}
    for item in items:
        if item.identities:
            continue
        group = by_digest.get(item.digest, [item])
        if any(other.identities for other in group):
            continue
        if item is not group[0]:
            continue
        kept.append(item)
        copies[item.path] = [other.path for other in group[1:]]
    return kept, copies


def repeated(items: list[FileCoverage]) -> list[tuple[FileCoverage, FileCoverage]]:
    """Pares (copia, original) de ficheros con contenido idéntico.

    El original es el primero por orden natural de ruta, salvo que alguno del
    grupo ya declare identidades: entonces ese. Los ficheros vacíos se ignoran.
    """
    by_digest: dict[str, list[FileCoverage]] = {}
    for item in items:
        if item.digest and item.lines:
            by_digest.setdefault(item.digest, []).append(item)
    result = []
    for group in by_digest.values():
        original = next((item for item in group if item.identities), group[0])
        result.extend((item, original) for item in group if item is not original)
    return sorted(result, key=lambda pair: _natural(pair[0].path))


def _content(path: Path) -> tuple[int, str]:
    try:
        data = path.read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return 0, ""
    return data.count(b"\n") + (bool(data) and not data.endswith(b"\n")), hashlib.sha256(data).hexdigest()
