"""Adaptador Markdown deliberadamente pequeño y sin dependencias externas."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .identity import Identity, SourceLocation
from .observation import Observation

HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
EXPLICIT_ID = re.compile(r"\s*\{#([A-Za-z][\w:.-]*)\}\s*$")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+['\"][^'\"]*['\"])?\s*\)")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
TYPED_ID = re.compile(r"^(REQ|DEC|TEST)-[A-Za-z0-9_.-]+\b", re.IGNORECASE)
KINDS = {"REQ": "requirement", "DEC": "decision", "TEST": "test"}


def github_slug(text: str) -> str:
    """Aproximación estable al identificador de encabezado de GitHub."""
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r"[\s]+", "-", text)


@dataclass(frozen=True)
class MarkdownResult:
    identities: tuple[Identity, ...]
    observations: tuple[Observation, ...]


class MarkdownAdapter:
    def read(self, path: Path, root: Path) -> MarkdownResult:
        document = Identity.document(path.resolve(), root.resolve())
        identities = [document]
        observations: list[Observation] = []
        anchors: dict[str, int] = {}
        current_identity = document
        in_fence = False
        fence_char = ""

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # El repositorio conserva algún documento histórico en ANSI.
            # cp1252 mantiene sus enlaces legibles en vez de inventar U+FFFD.
            text = path.read_text(encoding="cp1252")
        for number, line in enumerate(text.splitlines(), start=1):
            fence = FENCE.match(line)
            if fence:
                marker = fence.group(1)[0]
                if not in_fence:
                    in_fence, fence_char = True, marker
                elif marker == fence_char:
                    in_fence = False
                continue
            if in_fence:
                continue

            heading = HEADING.match(line)
            if heading:
                title = heading.group(2)
                explicit = EXPLICIT_ID.search(title)
                if explicit:
                    anchor = explicit.group(1)
                else:
                    anchor = github_slug(title)
                    occurrence = anchors.get(anchor, 0)
                    anchors[anchor] = occurrence + 1
                    if occurrence:
                        anchor = f"{anchor}-{occurrence}"
                semantic = TYPED_ID.match(title)
                semantic_id = semantic.group(0).upper() if semantic else None
                kind = KINDS[semantic.group(1).upper()] if semantic else "section"
                current_identity = Identity.section(
                    document, anchor, number, kind=kind, semantic_id=semantic_id
                )
                identities.append(current_identity)

            for link in LINK.finditer(line):
                target = link.group(1) or link.group(2)
                observations.append(
                    Observation(current_identity, target, SourceLocation(path.resolve(), number))
                )

        return MarkdownResult(tuple(identities), tuple(observations))
