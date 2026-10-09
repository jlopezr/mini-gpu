"""Carga todos los pases para registrarlos con `@register_pass`."""

from . import (
    branches, constprop, copyprop, dce, intrinsics, invert, jumps, kernels, licm, sharebase,
    ssy, stackslots, tailcalls, unreachable,
)

__all__ = [
    "branches", "constprop", "copyprop", "dce", "intrinsics", "invert", "jumps", "kernels",
    "licm", "sharebase", "ssy", "stackslots", "tailcalls", "unreachable",
]
