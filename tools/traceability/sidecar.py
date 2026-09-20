"""Adapter de sidecars `<basename>.trace.yaml` de v0.3."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from .diagnostic import Diagnostic
from .identity import Identity, Resource, SourceLocation
from .markdown import CORE_RELATIONS, CORE_TYPES, ID
from .observation import Observation

FIELDS = frozenset({
    "artifact", "type", "kind", "subjects", "status", "resource", "references",
}) | CORE_RELATIONS
RESOURCE_FIELDS = frozenset({"file", "revision", "url", "retrieval-date", "sha256"})


@dataclass(frozen=True)
class SidecarResult:
    resource: Resource
    identities: tuple[Identity, ...]
    observations: tuple[Observation, ...]
    diagnostics: tuple[Diagnostic, ...]


class SidecarAdapter:
    def read(self, path: Path, root: Path) -> SidecarResult:
        path, root = path.resolve(), root.resolve()
        location = SourceLocation(path, 1)
        diagnostics: list[Diagnostic] = []
        try:
            metadata = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            return SidecarResult(Resource(path), (), (), (
                Diagnostic("invalid-yaml", str(exc), location),
            ))
        if not isinstance(metadata, dict):
            return SidecarResult(Resource(path), (), (), (
                Diagnostic("invalid-sidecar", "el sidecar debe contener un mapping", location),
            ))
        for field in sorted(set(metadata) - FIELDS):
            diagnostics.append(Diagnostic("unknown-metadata", f"campo desconocido: '{field}'", location))

        artifact_id = metadata.get("artifact")
        artifact_type = metadata.get("type")
        if not isinstance(artifact_id, str) or not ID.fullmatch(artifact_id):
            diagnostics.append(Diagnostic("invalid-artifact-id", f"ID inválido: {artifact_id!r}", location))
            artifact = None
        else:
            if artifact_type not in CORE_TYPES:
                diagnostics.append(Diagnostic("invalid-artifact-type", f"type inválido o ausente: {artifact_type!r}", location))
            artifact = Identity(
                artifact_id, "artifact", location, artifact_type=artifact_type,
                metadata=metadata,
            )

        self._validate_resource(metadata.get("resource"), path, root, location, diagnostics)
        observations = self._relations(artifact, metadata, location, diagnostics) if artifact else []
        return SidecarResult(
            Resource(path), (artifact,) if artifact else (), tuple(observations), tuple(diagnostics)
        )

    def _validate_resource(self, value, sidecar, root, location, diagnostics):
        if not isinstance(value, dict):
            diagnostics.append(Diagnostic("invalid-sidecar-resource", "resource debe ser un mapping", location))
            return
        for field in sorted(set(value) - RESOURCE_FIELDS):
            diagnostics.append(Diagnostic("unknown-resource-field", f"campo desconocido: '{field}'", location))
        filename = value.get("file")
        if not isinstance(filename, str) or not filename:
            diagnostics.append(Diagnostic("invalid-sidecar-resource", "resource.file es obligatorio", location))
            return
        target = (sidecar.parent / filename).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            diagnostics.append(Diagnostic("outside-root", f"resource.file sale de la raíz: '{filename}'", location))
            return
        if not target.is_file():
            diagnostics.append(Diagnostic("missing-resource", f"no existe resource.file: '{filename}'", location))
            return
        expected = value.get("sha256")
        if expected is not None:
            if not isinstance(expected, str) or len(expected) != 64 or any(char not in "0123456789abcdefABCDEF" for char in expected):
                diagnostics.append(Diagnostic("invalid-checksum", "sha256 debe contener 64 dígitos hexadecimales", location))
            else:
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual.lower() != expected.lower():
                    diagnostics.append(Diagnostic("checksum-mismatch", f"sha256 no coincide para '{filename}'", location))

    def _relations(self, source, metadata, location, diagnostics):
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
                else:
                    diagnostics.append(Diagnostic("invalid-relation", f"target inválido en '{relation}'", location))
                    continue
                valid = {"coverage"} if relation == "verifies" else set()
                if set(attributes) - valid or (
                    "coverage" in attributes and attributes["coverage"] not in ("partial", "complete")
                ):
                    diagnostics.append(Diagnostic("invalid-relation-attributes", f"atributos inválidos para '{relation}'", location))
                result.append(Observation(source, relation, target, location, attributes))
        return result
