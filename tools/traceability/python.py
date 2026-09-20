"""Adapter Python nivel 1-2 de trazabilidad v0.3."""

import io
import re
import tokenize

from .annotated_code import AnnotatedCodeAdapter


class PythonAdapter(AnnotatedCodeAdapter):
    CACHE_VERSION = 2
    COMMENT = re.compile(r"^\s*#\s?(.*)$")
    ELEMENT = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
    element_name = "class/def"

    def comment_texts(self, lines: list[str]) -> dict[int, str]:
        """Use Python's lexer so hashes inside strings are never annotations."""
        source = "\n".join(lines) + "\n"
        comments = {}
        try:
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            for token in tokens:
                if token.type != tokenize.COMMENT:
                    continue
                line, column = token.start
                if lines[line - 1][:column].strip():
                    continue
                comments[line] = token.string[1:].lstrip()
        except (IndentationError, tokenize.TokenError):
            # Tokens emitted before a syntax error remain useful for diagnostics.
            pass
        return comments

    def allowed_between(self, line: str) -> bool:
        return bool(re.match(r"^\s*@[A-Za-z_][A-Za-z0-9_.]*(?:\(.*\))?\s*$", line))
