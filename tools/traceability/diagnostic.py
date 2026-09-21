"""Diagnósticos compartidos por adapters, builder y resolver."""

from dataclasses import dataclass
from pathlib import Path

from .identity import SourceLocation


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    location: SourceLocation
    severity: str = "error"

    def format(self, root: Path) -> str:
        return f"{self.location.display(root)}: {self.code}: {self.message}"
