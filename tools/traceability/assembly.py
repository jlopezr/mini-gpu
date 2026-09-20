"""Adapter de ensamblador MiniISA basado en labels."""

import re

from .annotated_code import AnnotatedCodeAdapter


class AssemblyAdapter(AnnotatedCodeAdapter):
    COMMENT = re.compile(r"^\s*;\s?(.*)$")
    ELEMENT = re.compile(r"^\s*([A-Za-z_.$][A-Za-z0-9_.$-]*)\s*:")
    element_name = "label"
