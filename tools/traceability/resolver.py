"""Resolución estricta de identidades y relaciones authored."""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostic import Diagnostic
from .model import Model
from .relation import Relation


@dataclass(frozen=True)
class Resolution:
    diagnostics: tuple[Diagnostic, ...]
    relations: tuple[Relation, ...]


class Resolver:
    def resolve(self, model: Model) -> list[Diagnostic]:
        return list(self.analyze(model).diagnostics)

    def analyze(self, model: Model) -> Resolution:
        diagnostics = list(model.diagnostics)
        by_key: dict[str, list] = {}
        for identity in model.identities:
            by_key.setdefault(identity.key, []).append(identity)
        for key, matches in by_key.items():
            if len(matches) > 1:
                first = matches[0].location.display(model.root)
                for duplicate in matches[1:]:
                    diagnostics.append(Diagnostic(
                        "duplicate-identity", f"'{key}' ya se declaró en {first}", duplicate.location
                    ))

        relations: list[Relation] = []
        authored: set[tuple] = set()
        for observation in model.observations:
            target_key = self._target_key(observation.source, observation.target)
            matches = by_key.get(target_key, [])
            if not matches:
                diagnostics.append(Diagnostic(
                    "unresolved-identity", f"identidad sin resolver: '{observation.target}'", observation.location
                ))
                continue
            if len(matches) > 1:
                diagnostics.append(Diagnostic(
                    "ambiguous-identity", f"identidad ambigua: '{observation.target}'", observation.location
                ))
                continue
            attributes = tuple(sorted(observation.attributes.items()))
            edge = (observation.source.key, observation.relation, target_key, attributes)
            if edge in authored:
                diagnostics.append(Diagnostic(
                    "duplicate-relation",
                    f"relación duplicada: {observation.source.key} --{observation.relation}--> {target_key}",
                    observation.location,
                ))
                continue
            authored.add(edge)
            relations.append(Relation(
                observation.source, matches[0], observation.relation, observation.attributes
            ))

        return Resolution(
            tuple(sorted(diagnostics, key=lambda item: (str(item.location.path), item.location.line, item.code))),
            tuple(sorted(relations, key=lambda item: (item.source.key, item.kind, item.target.key))),
        )

    @staticmethod
    def _target_key(source, target: str) -> str:
        if target.startswith(("#", "@", "::")):
            owner = source.key if source.element_type == "artifact" else source.owner
            return f"{owner}{target}"
        return target
