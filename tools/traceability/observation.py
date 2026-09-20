"""Referencias observadas por un adaptador de entrada."""

from dataclasses import dataclass

from .identity import Identity, SourceLocation


@dataclass(frozen=True)
class Observation:
    source: Identity
    target: str
    location: SourceLocation
