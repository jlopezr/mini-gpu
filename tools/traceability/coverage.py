"""Cobertura de marcado: qué ficheros descubiertos no declaran ninguna identidad."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import Model


@dataclass(frozen=True)
class FileCoverage:
    path: Path
    identities: int
    lines: int


def file_coverage(model: Model) -> list[FileCoverage]:
    """Un FileCoverage por Resource, con las identidades declaradas en él."""
    declared: dict[Path, int] = {}
    for identity in model.identities:
        path = identity.location.path.resolve()
        declared[path] = declared.get(path, 0) + 1
    result = []
    for resource in model.resources:
        path = resource.path.resolve()
        count = declared.get(path, 0)
        result.append(FileCoverage(path, count, 0 if count else _line_count(path)))
    return sorted(result, key=lambda item: item.path)


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0
