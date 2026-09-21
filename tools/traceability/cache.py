"""Caché descartable de fragmentos del Project Model por RESOURCE."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .diagnostic import Diagnostic
from .identity import Identity, Resource, SourceLocation
from .generation import GenerationBlock
from .observation import Observation

CACHE_SCHEMA = 2
CACHE_FILE = Path(".trace") / "cache-v1.json"


@dataclass(frozen=True)
class CachedResult:
    resource: Resource
    identities: tuple[Identity, ...]
    observations: tuple[Observation, ...]
    diagnostics: tuple[Diagnostic, ...]
    dependencies: tuple[Path, ...] = ()
    generation_blocks: tuple[GenerationBlock, ...] = ()


class GraphCache:
    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = root.resolve()
        self.path = self.root / CACHE_FILE
        self.enabled = enabled
        self.data = {"schema": CACHE_SCHEMA, "entries": {}, "deleted": {}}
        self.dirty = False
        if enabled:
            self._load()

    def get(self, path: Path, adapter_version: str) -> CachedResult | None:
        if not self.enabled:
            return None
        key = self._relative(path)
        entry = self.data["entries"].get(key)
        if not entry or entry.get("adapter") != adapter_version:
            return None
        if not self._same_file(path, entry):
            return None
        for dependency, fingerprint in entry.get("dependencies", {}).items():
            if not self._same_file(self.root / dependency, fingerprint):
                return None
        try:
            return self._deserialize(entry["fragment"])
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, path: Path, adapter_version: str, result) -> None:
        if not self.enabled:
            return
        key = self._relative(path)
        self.data["entries"][key] = {
            **self._fingerprint(path),
            "adapter": adapter_version,
            "dependencies": {
                self._relative(item): self._fingerprint(item)
                for item in getattr(result, "dependencies", ())
            },
            "fragment": self._serialize(result),
        }
        self.data["deleted"].pop(key, None)
        self.dirty = True

    def retain(self, paths: list[Path]) -> None:
        if not self.enabled:
            return
        wanted = {self._relative(path) for path in paths}
        entries = self.data["entries"]
        removed = set(entries) - wanted
        for key in removed:
            if not (self.root / key).exists():
                self.data["deleted"][key] = entries[key]
            del entries[key]
        self.dirty |= bool(removed)

    def deleted_results(self) -> tuple[CachedResult, ...]:
        """Return last-known fragments for resources no longer discovered."""
        if not self.enabled:
            return ()
        results = []
        for entry in self.data["deleted"].values():
            try:
                results.append(self._deserialize(entry["fragment"]))
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(results)

    def save(self) -> None:
        if not self.enabled or not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        self.dirty = False

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") == CACHE_SCHEMA and isinstance(data.get("entries"), dict):
                if not isinstance(data.get("deleted"), dict):
                    data["deleted"] = {}
                self.data = data
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            pass

    def _same_file(self, path: Path, fingerprint: dict) -> bool:
        if not fingerprint.get("exists", True):
            return not path.exists()
        try:
            stat = path.stat()
        except OSError:
            return False
        if stat.st_mtime_ns == fingerprint.get("mtime_ns") and stat.st_size == fingerprint.get("size"):
            return True
        if stat.st_size != fingerprint.get("size"):
            return False
        digest = self._hash(path)
        if digest != fingerprint.get("sha256"):
            return False
        fingerprint.update(mtime_ns=stat.st_mtime_ns, size=stat.st_size)
        self.dirty = True
        return True

    def _fingerprint(self, path: Path) -> dict:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        return {"exists": True, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "sha256": self._hash(path)}

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _serialize(self, result) -> dict:
        return {
            "resource": self._relative(result.resource.path),
            "identities": [self._identity(item) for item in result.identities],
            "observations": [{
                "source": item.source.key,
                "relation": item.relation,
                "target": item.target,
                "location": self._location(item.location),
                "attributes": self._json_value(item.attributes),
            } for item in result.observations],
            "diagnostics": [{
                "code": item.code, "message": item.message,
                "location": self._location(item.location), "severity": item.severity,
            } for item in result.diagnostics],
            "dependencies": [self._relative(item) for item in getattr(result, "dependencies", ())],
            "generation_blocks": [{
                "name": item.name, "generator": item.generator,
                "location": self._location(item.location),
                "options": self._json_value(item.options),
            } for item in getattr(result, "generation_blocks", ())],
        }

    def _deserialize(self, raw: dict) -> CachedResult:
        identities = tuple(self._read_identity(item) for item in raw["identities"])
        by_key = {item.key: item for item in identities}
        observations = tuple(Observation(
            by_key[item["source"]], item["relation"], item["target"],
            self._read_location(item["location"]), item.get("attributes", {}),
        ) for item in raw["observations"])
        diagnostics = tuple(Diagnostic(
            item["code"], item["message"], self._read_location(item["location"]),
            item.get("severity", "error"),
        ) for item in raw["diagnostics"])
        return CachedResult(
            Resource(self.root / raw["resource"]), identities, observations, diagnostics,
            tuple(self.root / item for item in raw.get("dependencies", [])),
            tuple(GenerationBlock(
                item["name"], item["generator"], self._read_location(item["location"]),
                item.get("options", {}),
            ) for item in raw.get("generation_blocks", [])),
        )

    def _identity(self, item: Identity) -> dict:
        return {
            "key": item.key, "element_type": item.element_type,
            "location": self._location(item.location), "artifact_type": item.artifact_type,
            "owner": item.owner, "parent_facet": item.parent_facet,
            "formal": item.formal, "metadata": self._json_value(item.metadata),
        }

    def _read_identity(self, item: dict) -> Identity:
        return Identity(
            item["key"], item["element_type"], self._read_location(item["location"]),
            item.get("artifact_type"), item.get("owner"), item.get("parent_facet"),
            item.get("formal", True), item.get("metadata", {}),
        )

    def _location(self, item: SourceLocation) -> dict:
        return {"path": self._relative(item.path), "line": item.line}

    def _read_location(self, item: dict) -> SourceLocation:
        return SourceLocation(self.root / item["path"], item["line"])

    def _json_value(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): self._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_value(item) for item in value]
        return str(value)
