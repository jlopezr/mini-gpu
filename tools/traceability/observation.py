"""Relaciones authored todavía pendientes de resolución."""

from dataclasses import dataclass, field
from typing import Any

from .identity import Identity, SourceLocation


@dataclass(frozen=True)
class Observation:
    source: Identity
    relation: str
    target: str
    location: SourceLocation
    attributes: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
