"""El registro de pases (`@register_pass`) y el orden por defecto."""
from __future__ import annotations

from collections.abc import Callable

from .model import Unit

# Un pase recibe la unidad (la modifica) y el diccionario de contadores de `--stats`.
Pass = Callable[[Unit, dict], None]

PASSES: dict[str, tuple[Pass, str]] = {}

# El orden importa: `kernels` deja los desplazamientos con registro; `jumps` y `constprop` simplifican
# antes de que `copyprop` y `licm` decidan que se repite y que registros sobran; `ssy` va al final,
# con el codigo ya definitivo.
DEFAULT_PASSES = ["intrinsics", "kernels", "jumps", "constprop", "copyprop", "licm", "ssy"]


def register_pass(name: str, doc: str) -> Callable[[Pass], Pass]:
    def wrap(fn: Pass) -> Pass:
        PASSES[name] = (fn, doc)
        return fn
    return wrap
