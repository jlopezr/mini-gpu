"""Registro común de generadores de documentación."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .graph import Graph
from .query import CORE_QUERIES


@dataclass(frozen=True)
class GenerationContext:
    root: Path
    graph: Graph | None = None
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratorDefinition:
    name: str
    function: Callable[[GenerationContext, dict], str]
    description: str


class GeneratorRegistry:
    def __init__(self) -> None:
        self._generators: dict[str, GeneratorDefinition] = {}

    @property
    def definitions(self):
        return MappingProxyType(self._generators)

    def generator(self, name=None, *, description: str | None = None):
        def decorate(function):
            registered_name = name if isinstance(name, str) else function.__name__.replace("_", "-")
            if registered_name in self._generators:
                raise ValueError(f"generator duplicado: '{registered_name}'")
            registered_description = description or (function.__doc__ or registered_name).strip()
            self._generators[registered_name] = GeneratorDefinition(
                registered_name, function, registered_description
            )
            return function
        if callable(name):
            return decorate(name)
        return decorate

    def run(self, name: str, context: GenerationContext, options: dict | None = None) -> str:
        definition = self._generators.get(name)
        if definition is None:
            raise ValueError(f"generator desconocido: '{name}'")
        result = definition.function(context, dict(options or {}))
        if not isinstance(result, str):
            raise ValueError(f"generator '{name}' no devolvió texto")
        return result


CORE_GENERATORS = GeneratorRegistry()
generator = CORE_GENERATORS.generator


@generator("trace.query", description="Materializa una query registrada como tabla Markdown")
def trace_query(context: GenerationContext, options: dict) -> str:
    if context.graph is None:
        raise ValueError("generator 'trace.query' requiere un grafo")
    unknown = set(options) - {"query", "arguments"}
    if unknown:
        raise ValueError(f"campos desconocidos para trace.query: {', '.join(sorted(unknown))}")
    query_name = options.get("query")
    arguments = options.get("arguments", [])
    if not isinstance(query_name, str) or not isinstance(arguments, list) or not all(
        isinstance(item, str) for item in arguments
    ):
        raise ValueError("trace.query requiere query y una lista arguments válida")
    result = CORE_QUERIES.run(query_name, context.graph, tuple(arguments))
    if not result.matches:
        return "_Sin resultados._"
    lines = ["| Identity | Type | Location | Reason |", "|---|---|---|---|"]
    for match in result.matches:
        identity = match.identity
        semantic_type = identity.artifact_type or identity.element_type
        lines.append(
            f"| `{identity.key}` | {semantic_type} | "
            f"`{identity.location.display(context.root)}` | {match.reason} |"
        )
    return "\n".join(lines)
