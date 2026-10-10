"""Lo que comparten TODOS los backends, de simulador y de placa."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def expand_for(names) -> frozenset:
    """Expande las capacidades implicadas.

    El import va dentro para no crear una dependencia circular: `run_tests`
    importa los backends al arrancar.
    """
    from run_tests import expand_capabilities

    return expand_capabilities(names)


def capabilities_of(versions: dict, version: str) -> frozenset:
    """Lo que tiene una versión, con las implicaciones ya expandidas."""
    return expand_for(versions[version]["capabilities"])


def missing_capabilities(case: dict, available: frozenset) -> list[str]:
    """Las capacidades que el caso pide y la versión no declara."""
    return [name for name in case.get("requires", []) if name not in available]
