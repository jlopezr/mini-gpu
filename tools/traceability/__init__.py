"""Modelo mínimo para comprobar trazabilidad entre documentos Markdown."""

from .diagnostic import Diagnostic
from .config import TraceConfig, load_config
from .cache import GraphCache
from .identity import Identity, Resource, SourceLocation
from .markdown import MarkdownAdapter
from .model import Model, ModelBuilder
from .observation import Observation
from .relation import Relation
from .resolver import Resolution, Resolver
from .systemverilog import SystemVerilogAdapter
from .sidecar import SidecarAdapter
from .python import PythonAdapter
from .assembly import AssemblyAdapter
from .impact import ImpactAnalyzer, ImpactedIdentity, ImpactHop, ImpactResult
from .graph import Graph, GraphHop

__all__ = [
    "Diagnostic",
    "Identity",
    "GraphCache",
    "MarkdownAdapter",
    "Model",
    "ModelBuilder",
    "Observation",
    "Relation",
    "Resource",
    "Resolution",
    "Resolver",
    "SourceLocation",
    "TraceConfig",
    "SystemVerilogAdapter",
    "SidecarAdapter",
    "PythonAdapter",
    "AssemblyAdapter",
    "ImpactAnalyzer",
    "ImpactedIdentity",
    "ImpactHop",
    "ImpactResult",
    "Graph",
    "GraphHop",
    "load_config",
]
