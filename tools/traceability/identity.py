"""Identidades semánticas independientes de su representación física."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, order=True)
class SourceLocation:
    path: Path
    line: int

    def display(self, root: Path) -> str:
        try:
            path = self.path.relative_to(root)
        except ValueError:
            path = self.path
        return f"{path.as_posix()}:{self.line}"


@dataclass(frozen=True)
class Resource:
    """Fichero físico examinado por un adaptador; no pertenece al grafo."""

    path: Path


@dataclass(frozen=True)
class Identity:
    """ARTIFACT o elemento local addressable del Project Model."""

    key: str
    element_type: str
    location: SourceLocation
    artifact_type: str | None = None
    owner: str | None = None
    parent_facet: str | None = None
    formal: bool = True
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
