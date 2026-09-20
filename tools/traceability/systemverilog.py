"""Adapter SystemVerilog nivel 1-2: anotaciones y módulos nombrados."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .diagnostic import Diagnostic
from .identity import Identity, Resource, SourceLocation
from .markdown import CORE_RELATIONS, CORE_TYPES, ID
from .observation import Observation

COMMENT = re.compile(r"^\s*//\s?(.*)$")
MODULE = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)\b")


@dataclass(frozen=True)
class SystemVerilogResult:
    resource: Resource
    identities: tuple[Identity, ...]
    observations: tuple[Observation, ...]
    diagnostics: tuple[Diagnostic, ...]
    dependencies: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Annotation:
    local_id: str | None
    command: str
    target: str | None
    attributes: dict[str, str]
    line: int


class SystemVerilogAdapter:
    CACHE_VERSION = 1

    def read(self, path: Path, root: Path) -> SystemVerilogResult:
        path = path.resolve()
        identities, observations, diagnostics = [], [], []
        group: list[Annotation] = []
        current_artifact: Identity | None = None
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        for number, line in enumerate(lines, start=1):
            comment = COMMENT.match(line)
            if comment:
                annotation = self._parse_annotation(comment.group(1), path, number, diagnostics)
                if annotation:
                    group.append(annotation)
                continue
            if not line.strip():
                continue
            module = MODULE.match(line)
            if module and group:
                current_artifact = self._bind_group(
                    path, module.group(1), group, current_artifact,
                    identities, observations, diagnostics,
                )
                group = []
                continue
            if group:
                diagnostics.append(Diagnostic(
                    "annotation-binding",
                    "el grupo de anotaciones no precede a un módulo reconocido",
                    SourceLocation(path, group[0].line),
                ))
                group = []
        if group:
            diagnostics.append(Diagnostic(
                "annotation-binding", "grupo de anotaciones sin elemento posterior",
                SourceLocation(path, group[0].line),
            ))
        return SystemVerilogResult(
            Resource(path), tuple(identities), tuple(observations), tuple(diagnostics)
        )

    def _parse_annotation(self, text, path, line, diagnostics):
        if "@" not in text:
            return None
        try:
            parts = shlex.split(text)
        except ValueError as exc:
            diagnostics.append(Diagnostic("invalid-annotation", str(exc), SourceLocation(path, line)))
            return None
        at = next((index for index, token in enumerate(parts) if token.startswith("@")), None)
        if at is None:
            return None
        if at > 1:
            diagnostics.append(Diagnostic("invalid-annotation", f"anotación inválida: '{text}'", SourceLocation(path, line)))
            return None
        local_id = parts[0] if at == 1 else None
        command = parts[at][1:]
        if command not in CORE_RELATIONS | {"artifact", "id"}:
            diagnostics.append(Diagnostic(
                "unknown-annotation", f"anotación desconocida: '@{command}'",
                SourceLocation(path, line),
            ))
            return None
        tail = parts[at + 1:]
        target = tail[0] if tail and "=" not in tail[0] else None
        attributes = {}
        for token in tail[1 if target else 0:]:
            if "=" not in token:
                diagnostics.append(Diagnostic("invalid-annotation", f"atributo inválido: '{token}'", SourceLocation(path, line)))
                continue
            key, value = token.split("=", 1)
            attributes[key] = value
        if local_id and not ID.fullmatch(local_id):
            diagnostics.append(Diagnostic("invalid-symbol-id", f"ID inválido: '{local_id}'", SourceLocation(path, line)))
        return Annotation(local_id, command, target, attributes, line)

    def _bind_group(self, path, module_name, group, current_artifact, identities, observations, diagnostics):
        artifacts = [item for item in group if item.command == "artifact"]
        ids = [item for item in group if item.command == "id" or item.local_id]
        if len(artifacts) > 1:
            diagnostics.append(Diagnostic("multiple-artifacts", "un grupo solo puede declarar un ARTIFACT", SourceLocation(path, artifacts[1].line)))
        if len(ids) > 1:
            diagnostics.append(Diagnostic("multiple-symbol-ids", "un grupo solo puede establecer un ID formal", SourceLocation(path, ids[1].line)))

        artifact = current_artifact
        if artifacts:
            declaration = artifacts[0]
            artifact_id = declaration.target
            artifact_type = declaration.attributes.get("type")
            location = SourceLocation(path, declaration.line)
            if not artifact_id or not ID.fullmatch(artifact_id):
                diagnostics.append(Diagnostic("invalid-artifact-id", f"ID inválido: {artifact_id!r}", location))
                artifact = None
            else:
                if artifact_type not in CORE_TYPES:
                    diagnostics.append(Diagnostic("invalid-artifact-type", f"type inválido o ausente: {artifact_type!r}", location))
                unknown = set(declaration.attributes) - {"type"}
                for field in sorted(unknown):
                    diagnostics.append(Diagnostic("unknown-annotation-attribute", f"atributo desconocido: '{field}'", location))
                artifact = Identity(artifact_id, "artifact", location, artifact_type=artifact_type)
                identities.append(artifact)

        relation_annotations = [item for item in group if item.command in CORE_RELATIONS]
        if artifacts:
            source = artifact
        elif relation_annotations or ids:
            if artifact is None:
                diagnostics.append(Diagnostic("symbol-without-artifact", "SYMBOL sin ARTIFACT contenedor", SourceLocation(path, group[0].line)))
                return current_artifact
            formal = ids[0] if ids else None
            if formal and formal.command == "id":
                local_id = formal.target
            elif formal:
                local_id = formal.local_id
            else:
                local_id = module_name
            if not local_id or not ID.fullmatch(local_id):
                diagnostics.append(Diagnostic("invalid-symbol-id", f"ID inválido: {local_id!r}", SourceLocation(path, group[0].line)))
                return artifact
            source = Identity(
                f"{artifact.key}::{local_id}", "symbol", SourceLocation(path, group[0].line),
                owner=artifact.key, formal=bool(formal),
            )
            identities.append(source)
        else:
            source = artifact

        for annotation in relation_annotations:
            if source is None or not annotation.target:
                diagnostics.append(Diagnostic("invalid-annotation", f"@{annotation.command} requiere target", SourceLocation(path, annotation.line)))
                continue
            valid = {"coverage"} if annotation.command == "verifies" else set()
            if set(annotation.attributes) - valid or (
                "coverage" in annotation.attributes and annotation.attributes["coverage"] not in ("partial", "complete")
            ):
                diagnostics.append(Diagnostic("invalid-relation-attributes", f"atributos inválidos para '{annotation.command}'", SourceLocation(path, annotation.line)))
            observations.append(Observation(
                source, annotation.command, annotation.target,
                SourceLocation(path, annotation.line), annotation.attributes,
            ))
        return artifact
