"""El registro de pases (`@register_pass`) y el orden por defecto."""
from __future__ import annotations

from typing import Callable



PASSES: dict[str, tuple[Callable, str]] = {}

DEFAULT_PASSES = ["intrinsics", "kernels", "jumps", "constprop", "copyprop", "licm", "ssy"]


def register_pass(name: str, doc: str):
    def wrap(fn):
        PASSES[name] = (fn, doc)
        return fn
    return wrap
