"""Relaciones semánticas resueltas entre identidades tipadas."""

from dataclasses import dataclass

from .identity import Identity


@dataclass(frozen=True)
class Relation:
    source: Identity
    target: Identity
    kind: str


def relation_kind(source: Identity, target: Identity) -> str:
    """Nombra la relación desde la perspectiva de quien contiene el enlace."""
    pair = (source.kind, target.kind)
    return {
        ("decision", "requirement"): "satisfies",
        ("requirement", "decision"): "specified-by",
        ("test", "requirement"): "verifies",
        ("requirement", "test"): "verified-by",
        ("test", "decision"): "verifies",
        ("decision", "test"): "verified-by",
    }.get(pair, "references")
