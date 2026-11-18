"""Carga todos los pases para registrarlos con `@register_pass`."""

from . import (
    boolean, branches, constprop, copyprop, dce, deadfuncs, deadsaves, deadstores, forward, inline, intrinsics,
    invert, jumps, kernels, lanestack, leafregs, licm, marks, noalias, retarget, sharebase, ssy, stackslots, strength, tailcalls, unreachable,
)

__all__ = [
    "boolean", "branches", "constprop", "copyprop", "dce", "deadfuncs", "deadsaves", "deadstores", "forward", "inline", "intrinsics", "invert",
    "jumps", "kernels", "lanestack", "leafregs", "licm", "marks", "noalias", "retarget", "sharebase", "ssy", "stackslots", "strength", "tailcalls", "unreachable",
]
