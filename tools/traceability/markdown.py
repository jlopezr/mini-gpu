"""Adapter para las declaraciones Markdown de traceability v0.3."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from .diagnostic import Diagnostic
from .identity import Identity, Resource, SourceLocation
from .observation import Observation

HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
EXPLICIT_ID = re.compile(r"\s*\{#([A-Za-z0-9_-]+)\}\s*$")
DIRECTIVE = re.compile(r"^\s*<!--\s*trace:(artifact|facet|relations)(?:\s+([^\s]+))?\s*$")
ID = re.compile(r"^[A-Za-z0-9_-]+$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
CORE_TYPES = frozenset({
    "need", "requirement", "decision", "specification", "implementation",
    "verification", "evidence", "source",
})
CORE_RELATIONS = frozenset({
    "derived-from", "refines", "addresses", "requires", "implements",
    "satisfies", "verifies", "produces", "supersedes",
})
ARTIFACT_FIELDS = frozenset({"type", "kind", "subjects", "status", "references", "members"}) | CORE_RELATIONS
FACET_FIELDS = frozenset({"kind"}) | CORE_RELATIONS


def derived_slug(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"\s*\{#[A-Za-z0-9_-]+\}\s*$", "", text)
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r"[\s]+", "-", text)


@dataclass(frozen=True)
class MarkdownResult:
    resource: Resource
    identities: tuple[Identity, ...]
    observations: tuple[Observation, ...]
    diagnostics: tuple[Diagnostic, ...]
    dependencies: tuple[Path, ...] = ()


class MarkdownAdapter:
    CACHE_VERSION = 1

    def read(self, path: Path, root: Path) -> MarkdownResult:
        path = path.resolve()
        resource = Resource(path)
        identities: list[Identity] = []
        observations: list[Observation] = []
        diagnostics: list[Diagnostic] = []
        artifact_stack: list[tuple[int, Identity]] = []
        facet_stack: list[tuple[int, Identity]] = []
        pending: tuple[str, str | None, dict, int] | None = None
        in_generated = False
        fence_char: str | None = None

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="cp1252")
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            number = index + 1
            if "<!-- gendoc:begin " in line:
                in_generated = True
            if in_generated:
                if "<!-- gendoc:end " in line:
                    in_generated = False
                index += 1
                continue

            fence = FENCE.match(line)
            if fence:
                marker = fence.group(1)[0]
                if fence_char is None:
                    fence_char = marker
                elif fence_char == marker:
                    fence_char = None
                index += 1
                continue
            if fence_char is not None:
                index += 1
                continue

            start = DIRECTIVE.match(line)
            if start:
                directive_line = number
                body = []
                index += 1
                while index < len(lines) and "-->" not in lines[index]:
                    body.append(lines[index])
                    index += 1
                if index == len(lines):
                    diagnostics.append(Diagnostic("unterminated-directive", "comentario trace sin cierre", SourceLocation(path, number)))
                    break
                try:
                    metadata = yaml.safe_load("\n".join(body)) or {}
                    if not isinstance(metadata, dict):
                        raise ValueError("la metadata debe ser un mapping YAML")
                except (yaml.YAMLError, ValueError) as exc:
                    diagnostics.append(Diagnostic("invalid-yaml", str(exc), SourceLocation(path, number)))
                    metadata = {}
                pending = (start.group(1), start.group(2), metadata, directive_line)
                index += 1
                continue

            heading = HEADING.match(line)
            if heading:
                level = len(heading.group(1))
                while artifact_stack and artifact_stack[-1][0] >= level:
                    artifact_stack.pop()
                while facet_stack and facet_stack[-1][0] >= level:
                    facet_stack.pop()
                title = heading.group(2)
                explicit = EXPLICIT_ID.search(title)
                if pending and pending[0] == "artifact":
                    artifact = self._artifact(path, pending, diagnostics)
                    if artifact:
                        identities.append(artifact)
                        artifact_stack.append((level, artifact))
                        facet_stack.clear()
                        observations.extend(self._relations(artifact, pending[2], path, pending[3], diagnostics, ARTIFACT_FIELDS))
                    pending = None
                elif pending and pending[0] == "facet":
                    if not artifact_stack:
                        diagnostics.append(Diagnostic(
                            "orphan-facet", "trace:facet debe estar dentro de un ARTIFACT",
                            SourceLocation(path, pending[3]),
                        ))
                        pending = None
                    else:
                        owner = artifact_stack[-1][1]
                        facet = self._facet(path, pending, owner, facet_stack, explicit, diagnostics)
                        if facet:
                            identities.append(facet)
                            section = Identity(
                                f"{owner.key}#{pending[1]}", "section", SourceLocation(path, number),
                                owner=owner.key, parent_facet=facet.key, formal=True,
                            )
                            identities.append(section)
                            facet_stack.append((level, facet))
                            observations.extend(self._relations(
                                facet, pending[2], path, pending[3], diagnostics, FACET_FIELDS
                            ))
                        pending = None
                elif artifact_stack:
                    owner = artifact_stack[-1][1]
                    local_id = explicit.group(1) if explicit else derived_slug(title)
                    section = Identity(
                        f"{owner.key}#{local_id}", "section", SourceLocation(path, number),
                        owner=owner.key,
                        parent_facet=facet_stack[-1][1].key if facet_stack else None,
                        formal=bool(explicit),
                    )
                    identities.append(section)
                    if pending and pending[0] == "relations":
                        if not explicit:
                            diagnostics.append(Diagnostic(
                                "relations-require-formal-id",
                                "trace:relations exige un ID formal de SECTION",
                                SourceLocation(path, pending[3]),
                            ))
                        else:
                            observations.extend(self._relations(section, pending[2], path, pending[3], diagnostics, CORE_RELATIONS))
                        pending = None
                elif pending:
                    diagnostics.append(Diagnostic("orphan-directive", "directiva fuera de un ARTIFACT", SourceLocation(path, pending[3])))
                    pending = None
            elif pending and line.strip():
                diagnostics.append(Diagnostic(
                    "directive-without-heading",
                    "la directiva trace debe preceder inmediatamente a un heading",
                    SourceLocation(path, pending[3]),
                ))
                pending = None
            index += 1

        return MarkdownResult(resource, tuple(identities), tuple(observations), tuple(diagnostics))

    def _artifact(self, path, pending, diagnostics):
        _, artifact_id, metadata, line = pending
        location = SourceLocation(path, line)
        if not artifact_id or not ID.fullmatch(artifact_id):
            diagnostics.append(Diagnostic("invalid-artifact-id", f"ID inválido: {artifact_id!r}", location))
            return None
        unknown = set(metadata) - ARTIFACT_FIELDS
        for field in sorted(unknown):
            diagnostics.append(Diagnostic("unknown-metadata", f"campo desconocido: '{field}'", location))
        artifact_type = metadata.get("type")
        if artifact_type not in CORE_TYPES:
            diagnostics.append(Diagnostic("invalid-artifact-type", f"type inválido o ausente: {artifact_type!r}", location))
        return Identity(artifact_id, "artifact", location, artifact_type=artifact_type, metadata=metadata)

    def _facet(self, path, pending, owner, facet_stack, explicit, diagnostics):
        _, local_id, metadata, line = pending
        location = SourceLocation(path, line)
        if not local_id or not ID.fullmatch(local_id):
            diagnostics.append(Diagnostic("invalid-facet-id", f"ID inválido: {local_id!r}", location))
            return None
        if not explicit:
            diagnostics.append(Diagnostic(
                "facet-requires-formal-section", "trace:facet exige un ID formal en su heading", location
            ))
            return None
        if explicit.group(1) != local_id:
            diagnostics.append(Diagnostic(
                "facet-section-id-mismatch",
                f"la FACET '{local_id}' debe asociarse a la SECTION '{{#{local_id}}}'",
                location,
            ))
            return None
        unknown = set(metadata) - FACET_FIELDS
        for field in sorted(unknown):
            diagnostics.append(Diagnostic("unknown-metadata", f"campo desconocido: '{field}'", location))
        kind = metadata.get("kind")
        if not isinstance(kind, str) or not kind:
            diagnostics.append(Diagnostic("invalid-facet-kind", "FACET requiere un kind", location))
        parent = facet_stack[-1][1].key if facet_stack else None
        return Identity(
            f"{owner.key}@{local_id}", "facet", location, owner=owner.key,
            parent_facet=parent, metadata=metadata,
        )

    def _relations(self, source, metadata, path, line, diagnostics, allowed):
        location = SourceLocation(path, line)
        unknown = set(metadata) - allowed
        for field in sorted(unknown):
            diagnostics.append(Diagnostic("unknown-metadata", f"campo desconocido: '{field}'", location))
        result = []
        for relation in CORE_RELATIONS:
            if relation not in metadata:
                continue
            values = metadata[relation]
            if not isinstance(values, list):
                diagnostics.append(Diagnostic("invalid-relation", f"'{relation}' debe ser una lista", location))
                continue
            for value in values:
                attributes = {}
                if isinstance(value, str):
                    target = value
                elif isinstance(value, dict) and isinstance(value.get("target"), str):
                    target = value["target"]
                    attributes = {key: item for key, item in value.items() if key != "target"}
                    valid = {"coverage"} if relation == "verifies" else set()
                    if set(attributes) - valid or ("coverage" in attributes and attributes["coverage"] not in ("partial", "complete")):
                        diagnostics.append(Diagnostic("invalid-relation-attributes", f"atributos inválidos para '{relation}'", location))
                else:
                    diagnostics.append(Diagnostic("invalid-relation", f"target inválido en '{relation}'", location))
                    continue
                result.append(Observation(source, relation, target, location, attributes))
        return result
