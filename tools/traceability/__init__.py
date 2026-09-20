"""Modelo mínimo para comprobar trazabilidad entre documentos Markdown."""

from .identity import Identity, SourceLocation
from .markdown import MarkdownAdapter
from .model import Model, ModelBuilder
from .observation import Observation
from .resolver import Diagnostic, Resolver

__all__ = [
    "Diagnostic",
    "Identity",
    "MarkdownAdapter",
    "Model",
    "ModelBuilder",
    "Observation",
    "Resolver",
    "SourceLocation",
]
