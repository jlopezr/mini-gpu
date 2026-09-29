"""Eliminación de copias idénticas de documentos, reapuntando los enlaces Markdown."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from .coverage import FileCoverage, repeated

INLINE_LINK = re.compile(r'(\]\()(<?)([^)\s>]+)(>?)((?:\s+"[^"]*")?\))')
REFERENCE_DEFINITION = re.compile(r'^(\s{0,3}\[[^\]]+\]:\s*)(<?)([^\s>]+)(>?)(.*)$')
FENCE = re.compile(r'^\s{0,3}(```|~~~)')
SCHEME = re.compile(r'^[a-z][a-z0-9+.-]*:', re.IGNORECASE)
MENTION_SUFFIXES = {".md", ".v", ".sv", ".py", ".asm", ".s", ".ini", ".txt", ".yaml", ".yml", ".toml", ".json", ".sh", ".bat", ".ps1"}
SKIPPED_DIRECTORIES = {".git", ".trace", "_build", "__pycache__", "node_modules"}


@dataclass(frozen=True)
class Rewrite:
    path: Path
    line: int
    start: int
    end: int
    old: str
    new: str


@dataclass(frozen=True)
class Mention:
    path: Path
    line: int
    text: str
    copy: Path


@dataclass
class Plan:
    deletions: list[tuple[Path, Path]] = field(default_factory=list)  # (copia, original)
    rewrites: list[Rewrite] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def build_plan(root: Path, items: list[FileCoverage], paths: list[Path],
               extensions: set[str]) -> Plan:
    plan = Plan()
    selected = [(path if path.is_absolute() else root / path).resolve() for path in paths]
    mapping: dict[Path, Path] = {}
    for copy, original in repeated(items):
        if copy.path.suffix.lower() not in extensions:
            continue
        if selected and not any(copy.path.is_relative_to(path) for path in selected):
            continue
        if copy.identities:
            plan.skipped.append((copy.path, "declara identidades trace"))
            continue
        mapping[copy.path] = original.path
    plan.deletions = sorted(mapping.items())

    rewritten_lines: set[tuple[Path, int]] = set()
    for item in items:
        if item.path.suffix.lower() != ".md" or item.path in mapping:
            continue
        for rewrite in _rewrites(item.path, mapping):
            plan.rewrites.append(rewrite)
            rewritten_lines.add((rewrite.path, rewrite.line))
    plan.mentions = _mentions(root, mapping, rewritten_lines)
    return plan


def apply_plan(plan: Plan) -> None:
    by_file: dict[Path, dict[int, list[Rewrite]]] = {}
    for rewrite in plan.rewrites:
        by_file.setdefault(rewrite.path, {}).setdefault(rewrite.line, []).append(rewrite)
    for path, lines in by_file.items():
        with path.open(encoding="utf-8", newline="") as handle:
            content = handle.readlines()
        for number, changes in lines.items():
            for change in sorted(changes, key=lambda item: item.start, reverse=True):
                text = content[number - 1]
                if text[change.start:change.end] != change.old:
                    raise ValueError(f"{path}:{number}: el fichero cambió desde el plan")
                content[number - 1] = text[:change.start] + change.new + text[change.end:]
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.writelines(content)
    for copy, _ in plan.deletions:
        copy.unlink()


def _rewrites(path: Path, mapping: dict[Path, Path]) -> list[Rewrite]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            lines = handle.readlines()
    except (OSError, UnicodeError):
        return []
    result: list[Rewrite] = []
    fenced = False
    for number, line in enumerate(lines, 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue

        def replace(match, number=number):
            target = match.group(3)
            new = _retarget(target, path.parent, mapping)
            if new is None:
                return match.group(0)
            result.append(Rewrite(path, number, match.start(3), match.end(3), target, new))
            return match.group(0)

        INLINE_LINK.sub(replace, line)
        definition = REFERENCE_DEFINITION.match(line)
        if definition:
            new = _retarget(definition.group(3), path.parent, mapping)
            if new is not None:
                result.append(Rewrite(path, number, definition.start(3), definition.end(3),
                                      definition.group(3), new))
    return result


def _retarget(target: str, base: Path, mapping: dict[Path, Path]) -> str | None:
    if target.startswith(("#", "/")) or SCHEME.match(target):
        return None
    location, hash_, fragment = target.partition("#")
    if not location:
        return None
    resolved = (base / unquote(location)).resolve()
    original = mapping.get(resolved)
    if original is None:
        return None
    relative = Path(os.path.relpath(original, base.resolve())).as_posix()
    if "%" in location:
        relative = quote(relative, safe="/._-~")
    return relative + hash_ + fragment


def _mentions(root: Path, mapping: dict[Path, Path], rewritten: set[tuple[Path, int]]) -> list[Mention]:
    by_directory: dict[Path, list[Path]] = {}
    for copy in mapping:
        parts = copy.relative_to(root).parts
        if len(parts) > 1:
            by_directory.setdefault(root / parts[0], []).append(copy)
    result: list[Mention] = []
    for directory, copies in by_directory.items():
        patterns = {copy: re.compile(rf"(?<![\w.-]){re.escape(copy.name)}(?![\w-])") for copy in copies}
        for current, dirs, files in os.walk(directory):
            dirs[:] = [name for name in dirs if name not in SKIPPED_DIRECTORIES]
            for name in files:
                path = Path(current, name).resolve()
                if path.suffix.lower() not in MENTION_SUFFIXES or path in mapping:
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeError):
                    continue
                for number, text in enumerate(lines, 1):
                    if (path, number) in rewritten:
                        continue
                    for copy, pattern in patterns.items():
                        if pattern.search(text):
                            result.append(Mention(path, number, text.strip(), copy))
    return sorted(result, key=lambda item: (item.path, item.line, item.copy))
