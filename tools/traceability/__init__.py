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
from .query import CORE_QUERIES, QueryDefinition, QueryMatch, QueryRegistry, QueryResult, query
from .rules import CORE_RULES, RuleDefinition, RuleFinding, RuleRegistry, rule
from .generator import (
    CORE_GENERATORS, GenerationContext, GeneratorDefinition, GeneratorRegistry, generator,
)

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
    "CORE_QUERIES",
    "QueryDefinition",
    "QueryMatch",
    "QueryRegistry",
    "QueryResult",
    "query",
    "CORE_RULES",
    "RuleDefinition",
    "RuleFinding",
    "RuleRegistry",
    "rule",
    "CORE_GENERATORS",
    "GenerationContext",
    "GeneratorDefinition",
    "GeneratorRegistry",
    "generator",
    "load_config",
]
