"""Construcción completa del Project Model antes de resolver relaciones."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import TraceConfig, load_config
from .cache import CachedResult, GraphCache
from .diagnostic import Diagnostic
from .identity import Identity, Resource
from .generation import GenerationBlock
from .markdown import MarkdownAdapter
from .observation import Observation
from .systemverilog import SystemVerilogAdapter
from .sidecar import SidecarAdapter
from .python import PythonAdapter
from .assembly import AssemblyAdapter

ADAPTERS = {
    ".md": MarkdownAdapter,
    ".sv": SystemVerilogAdapter,
    ".v": SystemVerilogAdapter,
    ".py": PythonAdapter,
    ".asm": AssemblyAdapter,
    ".s": AssemblyAdapter,
}


def adapter_for(path: Path):
    if path.name.endswith(".trace.yaml"):
        return SidecarAdapter
    return ADAPTERS.get(path.suffix.lower())

@dataclass(frozen=True)
class Model:
    root: Path
    config: TraceConfig
    resources: tuple[Resource, ...]
    identities: tuple[Identity, ...]
    observations: tuple[Observation, ...]
    diagnostics: tuple[Diagnostic, ...]
    cache_hits: int = 0
    cache_misses: int = 0
    deleted_fragments: tuple[CachedResult, ...] = ()
    generation_blocks: tuple[GenerationBlock, ...] = ()


class ModelBuilder:
    def __init__(self, adapter: MarkdownAdapter | None = None, use_cache: bool = True) -> None:
        self.adapter = adapter
        self.use_cache = use_cache

    def discover(self, root: Path, config: TraceConfig | None = None) -> list[Path]:
        root = root.resolve()
        config = config or load_config(root)[0]
        paths: set[Path] = set()
        for pattern in config.scan:
            paths.update(path.resolve() for path in root.glob(pattern)
                         if path.is_file() and adapter_for(path))
        return sorted(path for path in paths if not config.excludes(path, root))

    def build(self, root: Path, paths: Iterable[Path] | None = None) -> Model:
        root = root.resolve()
        config, config_diagnostics = load_config(root)
        discovered = self.discover(root, config)
        selected = set(discovered if paths is None else self._expand(root, paths))
        resources, identities, observations, generation_blocks = [], [], [], []
        diagnostics = list(config_diagnostics)
        cache = GraphCache(root, self.use_cache)
        hits = misses = 0
        for path in discovered:
            adapter = self.adapter or adapter_for(path)()
            adapter_version = (
                f"{adapter.__class__.__module__}.{adapter.__class__.__name__}:"
                f"{getattr(adapter, 'CACHE_VERSION', 1)}"
            )
            result = cache.get(path, adapter_version)
            if result is None:
                misses += 1
                result = adapter.read(path, root)
                cache.put(path, adapter_version, result)
            else:
                hits += 1
            resources.append(result.resource)
            identities.extend(result.identities)
            diagnostics.extend(result.diagnostics)
            generation_blocks.extend(getattr(result, "generation_blocks", ()))
            if path in selected:
                observations.extend(result.observations)
        cache.retain(discovered)
        deleted_fragments = cache.deleted_results()
        cache.save()
        return Model(
            root, config, tuple(resources), tuple(identities), tuple(observations),
            tuple(diagnostics), hits, misses, deleted_fragments,
            tuple(generation_blocks),
        )

    def _expand(self, root: Path, paths: Iterable[Path]) -> list[Path]:
        result: set[Path] = set()
        for supplied in paths:
            path = supplied if supplied.is_absolute() else root / supplied
            path = path.resolve()
            if path.is_dir():
                discovered = set(self.discover(root))
                result.update(item.resolve() for item in path.rglob("*") if item.resolve() in discovered)
            elif path.is_file() and adapter_for(path):
                if path not in self.discover(root):
                    raise ValueError(f"la ruta queda fuera de scan/exclude: {supplied}")
                result.add(path)
            else:
                raise ValueError(f"no existe un Markdown o directorio: {supplied}")
        return sorted(result)
