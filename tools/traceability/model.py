"""Construcción completa del Project Model antes de resolver relaciones."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .diagnostic import Diagnostic
from .identity import Identity, Resource
from .markdown import MarkdownAdapter
from .observation import Observation

DEFAULT_SKIPS = frozenset({".git", ".venv", "__pycache__", "_build", "node_modules"})


@dataclass(frozen=True)
class Model:
    root: Path
    resources: tuple[Resource, ...]
    identities: tuple[Identity, ...]
    observations: tuple[Observation, ...]
    diagnostics: tuple[Diagnostic, ...]


class ModelBuilder:
    def __init__(self, adapter: MarkdownAdapter | None = None) -> None:
        self.adapter = adapter or MarkdownAdapter()

    def discover(self, root: Path) -> list[Path]:
        root = root.resolve()
        return sorted(path for path in root.rglob("*.md")
                      if not any(part in DEFAULT_SKIPS for part in path.relative_to(root).parts))

    def build(self, root: Path, paths: Iterable[Path] | None = None) -> Model:
        root = root.resolve()
        discovered = self.discover(root)
        selected = set(discovered if paths is None else self._expand(root, paths))
        resources, identities, observations, diagnostics = [], [], [], []
        for path in discovered:
            result = self.adapter.read(path, root)
            resources.append(result.resource)
            identities.extend(result.identities)
            diagnostics.extend(result.diagnostics)
            if path in selected:
                observations.extend(result.observations)
        return Model(root, tuple(resources), tuple(identities), tuple(observations), tuple(diagnostics))

    def _expand(self, root: Path, paths: Iterable[Path]) -> list[Path]:
        result: set[Path] = set()
        for supplied in paths:
            path = supplied if supplied.is_absolute() else root / supplied
            path = path.resolve()
            if path.is_dir():
                result.update(item for item in path.rglob("*.md")
                              if not any(part in DEFAULT_SKIPS for part in item.relative_to(root).parts))
            elif path.is_file() and path.suffix.lower() == ".md":
                result.add(path)
            else:
                raise ValueError(f"no existe un Markdown o directorio: {supplied}")
        return sorted(result)
