"""Adapter SystemVerilog nivel 1-2 de trazabilidad v0.3."""

import re

from .annotated_code import AnnotatedCodeAdapter


class SystemVerilogAdapter(AnnotatedCodeAdapter):
    CACHE_VERSION = 2
    COMMENT = re.compile(r"^\s*//\s?(.*)$")
    ELEMENT = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)\b")
    element_name = "módulo"
