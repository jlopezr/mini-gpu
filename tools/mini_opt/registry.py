"""El registro de pases (`@register_pass`) y el orden por defecto."""
from __future__ import annotations

from collections.abc import Callable

from .model import Unit

# Un pase recibe la unidad (la modifica) y el diccionario de contadores de `--stats`.
Pass = Callable[[Unit, dict], None]

PASSES: dict[str, tuple[Pass, str]] = {}

# El orden importa: `deadfuncs` va dos veces: la primera, antes de todo, para que `licm` y los demas no vean las
# direcciones y las escrituras del codigo muerto; `kernelcalls` expande las llamadas de los kernels antes de que `kernels` los prepare;
# `stackslots` deja copias; las propagaciones descubren branches constantes;
# DCE limpia entre fases; `licm` se queda primero con los registros que necesita y `sharebase`
# usa los restantes; `inline` va cuando las hojas ya no tienen marco (`deadsaves`); tras el, `stackslots`
# pasa a copias los guardados de las funciones que se han quedado sin llamadas y `leafregs` les da a los
# R16..R29 el registro de la copia; las de detras limpian; `deadfuncs` (solo con --whole-program) vuelve cuando las demas ya han quitado las llamadas que
# sobraban (el `inline` deja funciones sin llamadas); `ssy` ve al final el CFG definitivo, `lanestack` comprueba los marcos definitivos, y `marks` (etiquetas del codigo expandido, para el perfil) va
# detras de todo porque una etiqueta parte un bloque.
DEFAULT_PASSES = [
    "deadfuncs", "intrinsics", "kernelcalls", "kernels", "stackslots", "jumps", "boolean", "forward", "deadstores", "constprop", "dce",
    "copyprop", "dce", "retarget", "branches", "unreachable", "argblock", "dce", "strength", "dce", "licm", "dce", "strength", "dce", "noalias",
    "sharebase", "deadsaves", "inline", "stackslots", "leafregs", "copyprop", "dce", "retarget", "dce", "jumps", "unreachable", "deadsaves",
    "tailcalls", "unreachable", "deadfuncs", "invert", "ssy", "lanestack", "marks",
]


def register_pass(name: str, doc: str) -> Callable[[Pass], Pass]:
    def wrap(fn: Pass) -> Pass:
        PASSES[name] = (fn, doc)
        return fn
    return wrap
