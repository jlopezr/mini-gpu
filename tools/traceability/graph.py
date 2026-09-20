"""Índices y navegación inmutables sobre un Project Model resuelto."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from types import MappingProxyType

from .identity import Identity
from .model import Model
from .relation import Relation
from .resolver import Resolution, Resolver


@dataclass(frozen=True)
class GraphHop:
    origin: str
    destination: str
    relation: str
    direction: str


class Graph:
    def __init__(self, model: Model, resolution: Resolution | None = None) -> None:
        self.model = model
        self.resolution = resolution or Resolver().analyze(model)
        grouped: dict[str, list[Identity]] = {}
        for identity in model.identities:
            grouped.setdefault(identity.key, []).append(identity)
        self.by_key = MappingProxyType({key: tuple(items) for key, items in grouped.items()})
        self.by_element_type = self._identity_index(lambda item: item.element_type)
        self.by_artifact_type = self._identity_index(lambda item: item.artifact_type)
        self.by_kind = self._identity_index(lambda item: item.metadata.get("kind"))
        subjects: dict[str, list[Identity]] = {}
        for identity in model.identities:
            for subject in identity.metadata.get("subjects", ()):
                if isinstance(subject, str):
                    subjects.setdefault(subject, []).append(identity)
        self.by_subject = MappingProxyType({key: tuple(sorted(items, key=lambda item: item.key))
                                            for key, items in subjects.items()})
        incoming: dict[str, list[Relation]] = {}
        outgoing: dict[str, list[Relation]] = {}
        for relation in self.resolution.relations:
            outgoing.setdefault(relation.source.key, []).append(relation)
            incoming.setdefault(relation.target.key, []).append(relation)
        self._incoming = MappingProxyType({key: tuple(sorted(items, key=self._relation_key))
                                           for key, items in incoming.items()})
        self._outgoing = MappingProxyType({key: tuple(sorted(items, key=self._relation_key))
                                           for key, items in outgoing.items()})
        children: dict[str, list[Identity]] = {}
        for identity in model.identities:
            parent = identity.parent_facet or identity.owner
            if parent:
                children.setdefault(parent, []).append(identity)
        self._children = MappingProxyType({key: tuple(sorted(items, key=lambda item: item.key))
                                           for key, items in children.items()})

    @staticmethod
    def _relation_key(relation: Relation) -> tuple[str, str, str]:
        return relation.kind, relation.source.key, relation.target.key

    def _identity_index(self, key_function):
        grouped: dict[str, list[Identity]] = {}
        for identity in self.model.identities:
            key = key_function(identity)
            if isinstance(key, str):
                grouped.setdefault(key, []).append(identity)
        return MappingProxyType({key: tuple(sorted(items, key=lambda item: item.key))
                                 for key, items in grouped.items()})

    def one(self, key: str) -> Identity:
        matches = self.by_key.get(key, ())
        if not matches:
            raise ValueError(f"no existe la identidad '{key}'")
        if len(matches) > 1:
            raise ValueError(f"la identidad '{key}' está duplicada")
        return matches[0]

    def identities(self, *, element_type: str | None = None, kind: str | None = None,
                   subject: str | None = None) -> tuple[Identity, ...]:
        result = []
        for identity in self.model.identities:
            semantic_type = identity.artifact_type if identity.element_type == "artifact" else identity.element_type
            if element_type and element_type not in {identity.element_type, semantic_type}:
                continue
            if kind and identity.metadata.get("kind") != kind:
                continue
            subjects = identity.metadata.get("subjects", ())
            if subject and (not isinstance(subjects, list) or subject not in subjects):
                continue
            result.append(identity)
        return tuple(sorted(result, key=lambda item: item.key))

    def incoming(self, key: str, relation: str | None = None) -> tuple[Relation, ...]:
        self.one(key)
        return tuple(item for item in self._incoming.get(key, ()) if relation is None or item.kind == relation)

    def outgoing(self, key: str, relation: str | None = None) -> tuple[Relation, ...]:
        self.one(key)
        return tuple(item for item in self._outgoing.get(key, ()) if relation is None or item.kind == relation)

    def children(self, key: str) -> tuple[Identity, ...]:
        self.one(key)
        return self._children.get(key, ())

    def shortest_path(self, start: str, end: str) -> tuple[GraphHop, ...] | None:
        self.one(start)
        self.one(end)
        if start == end:
            return ()
        visited = {start}
        queue = deque([(start, ())])
        while queue:
            key, path = queue.popleft()
            neighbours = []
            for edge in self._outgoing.get(key, ()):
                neighbours.append((edge.target.key, edge.kind, "outgoing"))
            for edge in self._incoming.get(key, ()):
                neighbours.append((edge.source.key, edge.kind, "incoming"))
            for destination, relation, direction in sorted(neighbours):
                if destination in visited:
                    continue
                route = path + (GraphHop(key, destination, relation, direction),)
                if destination == end:
                    return route
                visited.add(destination)
                queue.append((destination, route))
        return None

    def reachable(self, starts: tuple[Identity, ...], max_depth: int | None = None):
        """Yield identities with their shortest undirected semantic route."""
        visited = {item.key for item in starts}
        queue = deque((item.key, ()) for item in sorted(starts, key=lambda item: item.key))
        while queue:
            key, path = queue.popleft()
            if max_depth is not None and len(path) >= max_depth:
                continue
            neighbours = []
            for edge in self._outgoing.get(key, ()):
                neighbours.append((edge.target, edge.kind, "outgoing"))
            for edge in self._incoming.get(key, ()):
                neighbours.append((edge.source, edge.kind, "incoming"))
            for identity, relation, direction in sorted(neighbours, key=lambda item: (item[0].key, item[1], item[2])):
                if identity.key in visited:
                    continue
                route = path + (GraphHop(key, identity.key, relation, direction),)
                visited.add(identity.key)
                yield identity, route
                queue.append((identity.key, route))
