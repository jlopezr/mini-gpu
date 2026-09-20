"""Resolución de observaciones contra identidades y ficheros reales."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .identity import SourceLocation
from .model import Model

IGNORED_SCHEMES = frozenset({"http", "https", "mailto", "data"})
GENERATED_PARTS = frozenset({"_build"})


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    location: SourceLocation

    def format(self, root: Path) -> str:
        return f"{self.location.display(root)}: {self.code}: {self.message}"


class Resolver:
    def resolve(self, model: Model) -> list[Diagnostic]:
        diagnostics = self._duplicates(model)
        identities = {identity.key: identity for identity in model.identities}
        connections: set[tuple[str, str]] = set()
        for observation in model.observations:
            diagnostic, target = self._resolve_observation(model, identities, observation)
            if diagnostic:
                diagnostics.append(diagnostic)
            elif target and observation.source.semantic_id and target.semantic_id:
                connections.add((observation.source.semantic_id, target.semantic_id))
        diagnostics.extend(self._coverage(model, connections))
        return sorted(diagnostics, key=lambda item: (str(item.location.path), item.location.line, item.code))

    def _duplicates(self, model: Model) -> list[Diagnostic]:
        first = {}
        result = []
        for identity in model.identities:
            if identity.key in first:
                result.append(Diagnostic(
                    "duplicate-identity",
                    f"'{identity.key}' ya se declaró en {first[identity.key].display(model.root)}",
                    identity.location,
                ))
            else:
                first[identity.key] = identity.location
        semantic = {}
        for identity in model.identities:
            if not identity.semantic_id:
                continue
            if identity.semantic_id in semantic:
                result.append(Diagnostic(
                    "duplicate-semantic-id",
                    f"'{identity.semantic_id}' ya se declaró en {semantic[identity.semantic_id].display(model.root)}",
                    identity.location,
                ))
            else:
                semantic[identity.semantic_id] = identity.location
        return result

    def _resolve_observation(self, model, identities, observation):
        target = unquote(observation.target)
        parsed = urlsplit(target)
        if parsed.scheme.lower() in IGNORED_SCHEMES or target.startswith("//"):
            return None, None

        source_path = observation.source.location.path
        raw_path = parsed.path
        if not raw_path:
            destination = source_path
        elif raw_path.startswith("/"):
            destination = model.root / raw_path.lstrip("/")
        else:
            destination = source_path.parent / raw_path
        destination = destination.resolve()
        try:
            relative = destination.relative_to(model.root).as_posix()
        except ValueError:
            return Diagnostic("outside-root", f"'{target}' sale de la raíz", observation.location), None

        if raw_path and not destination.exists():
            if any(part in GENERATED_PARTS for part in Path(raw_path).parts):
                return None, None
            return Diagnostic("missing-target", f"no existe '{relative}'", observation.location), None

        if destination.is_dir() or (raw_path and destination.suffix.lower() != ".md"):
            if parsed.fragment:
                return Diagnostic("invalid-anchor", f"'{target}' no apunta a un Markdown", observation.location), None
            return None, None

        document_key = relative if raw_path else source_path.relative_to(model.root).as_posix()
        key = f"{document_key}#{parsed.fragment}" if parsed.fragment else document_key
        if key not in identities:
            kind = "ancla" if parsed.fragment else "documento"
            return Diagnostic("unresolved-identity", f"{kind} sin resolver: '{target}'", observation.location), None
        return None, identities[key]

    def _coverage(self, model: Model, connections: set[tuple[str, str]]) -> list[Diagnostic]:
        """Reglas mínimas: requisito diseñado y probado; decisión probada."""
        typed = [identity for identity in model.identities if identity.semantic_id]
        neighbors: dict[str, set[str]] = {identity.semantic_id: set() for identity in typed}
        for left, right in connections:
            neighbors.setdefault(left, set()).add(right)
            neighbors.setdefault(right, set()).add(left)
        kinds = {identity.semantic_id: identity.kind for identity in typed}
        diagnostics = []
        for identity in typed:
            connected_kinds = {kinds.get(item) for item in neighbors[identity.semantic_id]}
            required = ()
            if identity.kind == "requirement":
                required = (("decision", "uncovered-requirement", "no está conectado con una decisión"),
                            ("test", "unverified-requirement", "no está conectado con una prueba"))
            elif identity.kind == "decision":
                required = (("test", "unverified-decision", "no está conectado con una prueba"),)
            for target_kind, code, message in required:
                if target_kind not in connected_kinds:
                    diagnostics.append(Diagnostic(code, f"'{identity.semantic_id}' {message}", identity.location))
        return diagnostics
