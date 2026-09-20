"""Modelo mínimo para comprobar trazabilidad entre documentos Markdown."""

from .diagnostic import Diagnostic
from .identity import Identity, Resource, SourceLocation
from .markdown import MarkdownAdapter
from .model import Model, ModelBuilder
from .observation import Observation
from .relation import Relation
from .resolver import Resolution, Resolver

__all__ = [
    "Diagnostic",
    "Identity",
    "MarkdownAdapter",
    "Model",
    "ModelBuilder",
    "Observation",
    "Relation",
    "Resource",
    "Resolution",
    "Resolver",
    "SourceLocation",
]
