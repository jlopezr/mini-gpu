"""Carga todos los pases para registrarlos con `@register_pass`."""

from . import (
    boolean, branches, constprop, copyprop, dce, deadsaves, forward, intrinsics, invert, jumps,
    kernels, licm, sharebase, ssy, stackslots, tailcalls, unreachable,
)

__all__ = [
    "boolean", "branches", "constprop", "copyprop", "dce", "deadsaves", "forward", "intrinsics", "invert",
    "jumps", "kernels", "licm", "sharebase", "ssy", "stackslots", "tailcalls", "unreachable",
]
