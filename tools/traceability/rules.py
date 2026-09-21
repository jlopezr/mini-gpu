"""Reglas Python de política ejecutadas sobre un grafo resuelto."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable

from .diagnostic import Diagnostic
from .graph import Graph
from .identity import Identity, SourceLocation


@dataclass(frozen=True)
class RuleFinding:
    identity: Identity
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class RuleDefinition:
    name: str
    function: Callable[[Graph], Iterable[RuleFinding]]
    description: str


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, RuleDefinition] = {}

    @property
    def definitions(self):
        return MappingProxyType(self._rules)

    def rule(self, name=None, *, description: str | None = None):
        def decorate(function):
            registered_name = name if isinstance(name, str) else function.__name__.replace("_", "-")
            if registered_name in self._rules:
                raise ValueError(f"rule duplicada: '{registered_name}'")
            registered_description = description or (function.__doc__ or registered_name).strip()
            self._rules[registered_name] = RuleDefinition(
                registered_name, function, registered_description
            )
            return function
        if callable(name):
            return decorate(name)
        return decorate

    def run(self, graph: Graph, names: tuple[str, ...]) -> tuple[Diagnostic, ...]:
        diagnostics = []
        for name in names:
            definition = self._rules.get(name)
            if definition is None:
                location = graph.model.config.path or graph.model.root / "trace.yaml"
                diagnostics.append(Diagnostic(
                    "unknown-rule", f"rule desconocida: '{name}'", SourceLocation(location, 1)
                ))
                continue
            for finding in definition.function(graph):
                if finding.severity not in {"error", "warning"}:
                    diagnostics.append(Diagnostic(
                        "invalid-rule-severity",
                        f"rule '{name}' devolvió severity inválida: {finding.severity!r}",
                        finding.identity.location,
                    ))
                    continue
                diagnostics.append(Diagnostic(
                    f"rule:{name}", finding.message, finding.identity.location, finding.severity
                ))
        return tuple(sorted(diagnostics, key=lambda item: (
            str(item.location.path), item.location.line, item.code
        )))


CORE_RULES = RuleRegistry()
rule = CORE_RULES.rule


def _accepted(graph: Graph, artifact_type: str):
    return (
        item for item in graph.by_artifact_type.get(artifact_type, ())
        if item.metadata.get("status") == "accepted"
    )


@rule(description="Todo requirement accepted debe estar satisfecho")
def accepted_requirements_satisfied(graph: Graph):
    for identity in _accepted(graph, "requirement"):
        if not graph.incoming(identity.key, "satisfies"):
            yield RuleFinding(identity, "requirement accepted sin relación entrante satisfies")


@rule(description="Toda specification accepted debe estar implementada")
def accepted_specifications_implemented(graph: Graph):
    for identity in _accepted(graph, "specification"):
        if not graph.incoming(identity.key, "implements"):
            yield RuleFinding(identity, "specification accepted sin relación entrante implements")


@rule(description="Todo target accepted debe tener verificación completa")
def accepted_targets_fully_verified(graph: Graph):
    for artifact_type in ("requirement", "specification"):
        for identity in _accepted(graph, artifact_type):
            relations = graph.incoming(identity.key, "verifies")
            if not any(item.attributes.get("coverage") == "complete" for item in relations):
                yield RuleFinding(identity, "target accepted sin verifies coverage=complete")
