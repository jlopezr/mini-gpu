"""El registro de pases (`@register_pass`) y el orden por defecto."""
from __future__ import annotations

from collections.abc import Callable

from .model import Unit

# Un pase recibe la unidad (la modifica) y el diccionario de contadores de `--stats`.
Pass = Callable[[Unit, dict], None]

PASSES: dict[str, tuple[Pass, str]] = {}

# El orden importa: las propagaciones descubren branches constantes; al podarlos aparecen bloques
# inalcanzables y mas codigo muerto; `ssy` va al final, con el CFG ya definitivo.
DEFAULT_PASSES = [
    "intrinsics", "kernels", "jumps", "constprop", "dce", "copyprop", "dce",
    "branches", "unreachable", "licm", "dce", "tailcalls", "unreachable", "ssy",
]


def register_pass(name: str, doc: str) -> Callable[[Pass], Pass]:
    def wrap(fn: Pass) -> Pass:
        PASSES[name] = (fn, doc)
        return fn
    return wrap
