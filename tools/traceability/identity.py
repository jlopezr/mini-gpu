"""Identidades estables de los elementos observables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
class Identity:
    """Nombre canónico de un documento o de una sección Markdown."""

    key: str
    kind: str
    location: SourceLocation
    semantic_id: str | None = None

    @classmethod
    def document(cls, path: Path, root: Path) -> "Identity":
        return cls(path.relative_to(root).as_posix(), "document", SourceLocation(path, 1))

    @classmethod
    def section(
        cls,
        document: "Identity",
        anchor: str,
        line: int,
        kind: str = "section",
        semantic_id: str | None = None,
    ) -> "Identity":
        return cls(
            f"{document.key}#{anchor}",
            kind,
            SourceLocation(document.location.path, line),
            semantic_id,
        )
