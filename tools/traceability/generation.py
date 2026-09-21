"""Declaración cacheable de un bloque de documentación generada."""

from dataclasses import dataclass, field
from typing import Any

from .identity import SourceLocation


@dataclass(frozen=True)
class GenerationBlock:
    name: str
    generator: str
    location: SourceLocation
    options: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
