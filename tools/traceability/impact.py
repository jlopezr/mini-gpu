"""Análisis explicable de impacto sobre relaciones explícitas."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

from .identity import Identity
from .model import Model
from .relation import Relation
from .resolver import Resolution, Resolver


@dataclass(frozen=True)
class ImpactHop:
    origin: str
    destination: str
    relation: str
    direction: str


@dataclass(frozen=True)
class ImpactedIdentity:
    identity: Identity
    depth: int
    path: tuple[ImpactHop, ...]


@dataclass(frozen=True)
class ImpactResult:
    seeds: tuple[Identity, ...]
    impacted: tuple[ImpactedIdentity, ...]
    resolution: Resolution
    deleted_resource: bool = False


class ImpactAnalyzer:
    def analyze(self, model: Model, requested: str, max_depth: int | None = None) -> ImpactResult:
        if max_depth is not None and max_depth < 1:
            raise ValueError("--depth debe ser al menos 1")
        working, seeds, deleted = self._select(model, requested)
        resolution = Resolver().analyze(working)
        if not seeds:
            raise ValueError(f"no existe la identidad o recurso '{requested}'")

        adjacency: dict[str, list[tuple[Identity, Relation, str]]] = {}
        for relation in resolution.relations:
            adjacency.setdefault(relation.source.key, []).append((relation.target, relation, "outgoing"))
            adjacency.setdefault(relation.target.key, []).append((relation.source, relation, "incoming"))
        for edges in adjacency.values():
            edges.sort(key=lambda item: (item[0].key, item[1].kind, item[2]))

        seed_keys = {item.key for item in seeds}
        visited = set(seed_keys)
        queue = deque((item, ()) for item in sorted(seeds, key=lambda item: item.key))
        impacted = []
        while queue:
            identity, path = queue.popleft()
            if max_depth is not None and len(path) >= max_depth:
                continue
            for neighbour, relation, direction in adjacency.get(identity.key, ()):
                if neighbour.key in visited:
                    continue
                hop = ImpactHop(identity.key, neighbour.key, relation.kind, direction)
                route = path + (hop,)
                visited.add(neighbour.key)
                impacted.append(ImpactedIdentity(neighbour, len(route), route))
                queue.append((neighbour, route))
        impacted.sort(key=lambda item: (item.depth, item.identity.key))
        return ImpactResult(tuple(seeds), tuple(impacted), resolution, deleted)

    def _select(self, model: Model, requested: str) -> tuple[Model, list[Identity], bool]:
        exact = [item for item in model.identities if item.key == requested]
        if exact:
            return model, exact, False

        candidate = Path(requested)
        candidate = candidate.resolve() if candidate.is_absolute() else (model.root / candidate).resolve()
        try:
            candidate.relative_to(model.root)
        except ValueError as exc:
            raise ValueError(f"el recurso queda fuera del proyecto: {requested}") from exc

        current = [item for item in model.identities if item.location.path.resolve() == candidate]
        if current:
            return model, current, False
        for fragment in model.deleted_fragments:
            if fragment.resource.path.resolve() != candidate:
                continue
            augmented = replace(
                model,
                identities=model.identities + fragment.identities,
                observations=model.observations + fragment.observations,
            )
            return augmented, list(fragment.identities), True
        return model, [], False
