"""Carga todos los pases para registrarlos con `@register_pass`."""

from . import (
    boolean, branches, constprop, copyprop, dce, deadsaves, deadstores, forward, intrinsics, invert,
    jumps, kernels, licm, sharebase, ssy, stackslots, strength, tailcalls, unreachable,
)

__all__ = [
    "boolean", "branches", "constprop", "copyprop", "dce", "deadsaves", "deadstores", "forward", "intrinsics", "invert",
    "jumps", "kernels", "licm", "sharebase", "ssy", "stackslots", "strength", "tailcalls", "unreachable",
]
