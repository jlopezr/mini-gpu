"""Edge semántico explícito y resuelto."""

from dataclasses import dataclass, field
from typing import Any

from .identity import Identity


@dataclass(frozen=True)
class Relation:
    source: Identity
    target: Identity
    kind: str
    attributes: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
