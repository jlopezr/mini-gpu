"""El registro de pases (`@register_pass`) y el orden por defecto."""
from __future__ import annotations

from collections.abc import Callable

from .model import Unit

# Un pase recibe la unidad (la modifica) y el diccionario de contadores de `--stats`.
Pass = Callable[[Unit, dict], None]

PASSES: dict[str, tuple[Pass, str]] = {}

# El orden importa: `stackslots` deja copias; las propagaciones descubren branches constantes;
# DCE limpia entre fases; `licm` se queda primero con los registros que necesita y `sharebase`
# usa los restantes; `ssy` ve al final el CFG definitivo.
DEFAULT_PASSES = [
    "intrinsics", "kernels", "stackslots", "jumps", "boolean", "forward", "deadstores", "constprop", "dce",
    "copyprop", "dce", "branches", "unreachable", "licm", "dce",
    "sharebase", "deadsaves", "tailcalls", "unreachable", "invert", "ssy",
]


def register_pass(name: str, doc: str) -> Callable[[Pass], Pass]:
    def wrap(fn: Pass) -> Pass:
        PASSES[name] = (fn, doc)
        return fn
    return wrap
