"""Carga estricta de la parte de discovery de trace.yaml v0.3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from .diagnostic import Diagnostic
from .identity import SourceLocation

CONFIG_FIELDS = frozenset({"project", "version", "scan", "exclude"})
DEFAULT_SCAN = ("**/*.md",)
DEFAULT_EXCLUDE = (".git/**", ".venv/**", "**/__pycache__/**", "**/_build/**", "**/node_modules/**")


@dataclass(frozen=True)
class TraceConfig:
    project: str | None
    version: int
    scan: tuple[str, ...]
    exclude: tuple[str, ...]
    path: Path | None = None

    def excludes(self, path: Path, root: Path) -> bool:
        relative = PurePosixPath(path.relative_to(root).as_posix())
        return any(relative.match(pattern) or _prefix_match(relative, pattern) for pattern in self.exclude)


def _prefix_match(path: PurePosixPath, pattern: str) -> bool:
    if not pattern.endswith("/**"):
        return False
    prefix = pattern[:-3].rstrip("/")
    value = path.as_posix()
    if "/" not in prefix and prefix.startswith("**"):
        name = prefix.removeprefix("**/")
        return name in path.parts
    return value == prefix or value.startswith(f"{prefix}/")


def load_config(root: Path) -> tuple[TraceConfig, tuple[Diagnostic, ...]]:
    path = root / "trace.yaml"
    if not path.exists():
        return TraceConfig(None, 1, DEFAULT_SCAN, DEFAULT_EXCLUDE), ()
    location = SourceLocation(path, 1)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return TraceConfig(None, 1, (), DEFAULT_EXCLUDE, path), (
            Diagnostic("invalid-config", str(exc), location),
        )
    diagnostics = []
    if not isinstance(raw, dict):
        return TraceConfig(None, 1, (), DEFAULT_EXCLUDE, path), (
            Diagnostic("invalid-config", "trace.yaml debe contener un mapping", location),
        )
    for field in sorted(set(raw) - CONFIG_FIELDS):
        diagnostics.append(Diagnostic("unknown-config-field", f"campo desconocido: '{field}'", location))
    project = raw.get("project")
    version = raw.get("version", 1)
    scan = raw.get("scan", list(DEFAULT_SCAN))
    exclude = raw.get("exclude", list(DEFAULT_EXCLUDE))
    if project is not None and not isinstance(project, str):
        diagnostics.append(Diagnostic("invalid-config", "project debe ser texto", location))
        project = None
    if not isinstance(version, int):
        diagnostics.append(Diagnostic("invalid-config", "version debe ser un entero", location))
        version = 1
    elif version != 1:
        diagnostics.append(Diagnostic("unsupported-config-version", f"version no soportada: {version!r}", location))
    scan = _pattern_list("scan", scan, diagnostics, location)
    exclude = _pattern_list("exclude", exclude, diagnostics, location)
    return TraceConfig(project, version, scan, exclude, path), tuple(diagnostics)


def _pattern_list(name, value, diagnostics, location) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        diagnostics.append(Diagnostic("invalid-config", f"{name} debe ser una lista de patrones", location))
        return ()
    result = []
    for pattern in value:
        parsed = PurePosixPath(pattern.replace("\\", "/"))
        if parsed.is_absolute() or ".." in parsed.parts or ":" in parsed.parts[0]:
            diagnostics.append(Diagnostic(
                "invalid-config", f"{name} contiene un patrón fuera de la raíz: '{pattern}'", location
            ))
            continue
        result.append(pattern)
    return tuple(result)
