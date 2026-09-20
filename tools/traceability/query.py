"""Queries Python registradas sobre la API pública del grafo."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable

from .graph import Graph
from .identity import Identity
from .relation import Relation


@dataclass(frozen=True)
class QueryMatch:
    identity: Identity
    reason: str
    relations: tuple[Relation, ...] = ()


@dataclass(frozen=True)
class QueryDefinition:
    name: str
    function: Callable[..., Iterable[QueryMatch]]
    description: str
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryResult:
    query: QueryDefinition
    arguments: tuple[str, ...]
    matches: tuple[QueryMatch, ...]


class QueryRegistry:
    def __init__(self) -> None:
        self._queries: dict[str, QueryDefinition] = {}

    @property
    def definitions(self):
        return MappingProxyType(self._queries)

    def query(self, name=None, *, description: str | None = None, arguments: tuple[str, ...] = ()):
        def decorate(function):
            registered_name = name if isinstance(name, str) else function.__name__.replace("_", "-")
            if registered_name in self._queries:
                raise ValueError(f"query duplicada: '{registered_name}'")
            registered_description = description or (function.__doc__ or registered_name).strip()
            self._queries[registered_name] = QueryDefinition(
                registered_name, function, registered_description, arguments
            )
            return function
        if callable(name):
            return decorate(name)
        return decorate

    def run(self, name: str, graph: Graph, arguments: tuple[str, ...] = ()) -> QueryResult:
        definition = self._queries.get(name)
        if definition is None:
            raise ValueError(f"query desconocida: '{name}'")
        if len(arguments) != len(definition.arguments):
            expected = " ".join(f"<{item}>" for item in definition.arguments) or "sin argumentos"
            raise ValueError(
                f"query '{name}' espera {len(definition.arguments)} argumento(s): {expected}"
            )
        matches = tuple(sorted(definition.function(graph, *arguments), key=lambda item: item.identity.key))
        return QueryResult(definition, arguments, matches)


CORE_QUERIES = QueryRegistry()
query = CORE_QUERIES.query


def _is_owned_by(graph: Graph, identity: Identity, artifact_types: set[str]) -> bool:
    if identity.element_type == "artifact":
        return identity.artifact_type in artifact_types
    if identity.element_type not in {"section", "facet"} or not identity.owner:
        return False
    owners = graph.by_key.get(identity.owner, ())
    return len(owners) == 1 and owners[0].artifact_type in artifact_types


def _missing_incoming(graph: Graph, artifact_types: set[str], relation: str,
                      reason: str, predicate=None):
    for identity in graph.identities():
        if not _is_owned_by(graph, identity, artifact_types):
            continue
        relations = graph.incoming(identity.key, relation)
        if not relations or (predicate and not any(predicate(item) for item in relations)):
            yield QueryMatch(identity, reason, relations)


@query("unimplemented", description="Especificaciones sin relación entrante implements")
def unimplemented(graph: Graph):
    return _missing_incoming(
        graph, {"specification"}, "implements",
        "no tiene ninguna relación entrante implements",
    )


@query("unverified", description="Requirements y especificaciones sin ninguna verificación")
def unverified(graph: Graph):
    return _missing_incoming(
        graph, {"requirement", "specification"}, "verifies",
        "no tiene ninguna relación entrante verifies",
    )


@query("not-fully-verified", description="Targets sin verificación coverage=complete")
def not_fully_verified(graph: Graph):
    return _missing_incoming(
        graph, {"requirement", "specification"}, "verifies",
        "no tiene ninguna relación verifies con coverage=complete",
        lambda item: item.attributes.get("coverage") == "complete",
    )


@query("unsatisfied", description="Requirements sin relación entrante satisfies")
def unsatisfied(graph: Graph):
    for identity in graph.by_artifact_type.get("requirement", ()):
        relations = graph.incoming(identity.key, "satisfies")
        if not relations:
            yield QueryMatch(identity, "no tiene ninguna relación entrante satisfies")


def _related(graph: Graph, target: str, relation: str, reason: str):
    for edge in graph.incoming(target, relation):
        yield QueryMatch(edge.source, reason, (edge,))


@query("implementations-of", description="Implementaciones de una identidad", arguments=("identity",))
def implementations_of(graph: Graph, target: str):
    return _related(graph, target, "implements", f"implementa {target}")


@query("verifications-of", description="Verificaciones de una identidad", arguments=("identity",))
def verifications_of(graph: Graph, target: str):
    return _related(graph, target, "verifies", f"verifica {target}")
