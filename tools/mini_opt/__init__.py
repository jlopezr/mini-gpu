"""Filtro entre el `.s` del compilador y `mini-asm`: aplica pases a un `.s`.

    mini-lcc --no-crt kernels.c -o kernels.s
    mini-opt kernels.s -o kernels.opt.s --stats
    mini-asm programa.asm -o programa.bin       # con `.include "kernels.opt.s"`

Juntar unidades lo hace el ensamblador con `.include` (y desde que las `L.n` de lcc
son privadas de cada fichero, dos `.s` no chocan); el arranque, `1.isa/runtime/crt0.s`.
Este filtro solo transforma un `.s` en otro: lo trocea en funciones, calcula su grafo de
flujo y la vida de sus registros, y aplica los pases pedidos (`--list-passes`).

Un modulo por cosa:

    model.py      el `.s` troceado: lineas, funciones, unidades (parse_unit / render_unit)
    isa.py        que lee y escribe cada instruccion (defs_uses) y los conjuntos de mnemonicos
    flow.py       bloques basicos, vida de registros, dominadores y bucles
    dead.py       codigo muerto (lo usan constprop y copyprop)
    registry.py   el registro de pases (`@register_pass`) y el orden por defecto
    cli.py        `optimize`, `--stats` y la linea de ordenes
    passes/       un fichero por pase: intrinsics, kernels, jumps, constprop, copyprop, licm, ssy

El pase `intrinsics` es el equivalente a `threadIdx`/`__syncthreads` de CUDA sin tocar `rcc`:
el C declara `extern volatile int __gpu_tid;` y lo lee como una variable; el pase convierte el
par `LI r,__gpu_tid ; LOAD d,r,0` en `GETTID d`. Para anadir otro intrinseco basta una entrada
en `INTRINSIC_LOADS` o `INTRINSIC_STORES`; para otra transformacion, un fichero en `passes/` con
una funcion `@register_pass` (y un `import` en `passes/__init__.py`).
"""
from __future__ import annotations

from . import passes as passes
from .cli import count_instructions, main, optimize, print_stats
from .dead import remove_dead
from .flow import (Block, build_cfg, dominators, immediate_postdominator, live_after, live_in_entry,
                   liveness, natural_loops, postdominators)
from .isa import defs_uses, number, reg_of
from .model import Function, Line, OptError, Unit, directive_parts, parse_unit, render_unit
from .passes.constprop import pass_constprop
from .passes.copyprop import pass_copyprop
from .passes.intrinsics import pass_intrinsics
from .passes.jumps import pass_jumps
from .passes.kernels import pass_kernels
from .passes.licm import pass_licm
from .passes.ssy import pass_ssy
from .registry import DEFAULT_PASSES, PASSES, register_pass

__all__ = [
    "Block", "DEFAULT_PASSES", "Function", "Line", "OptError", "PASSES", "Unit", "build_cfg",
    "count_instructions", "defs_uses", "directive_parts", "dominators", "immediate_postdominator",
    "live_after", "live_in_entry", "liveness", "main", "natural_loops", "number", "optimize",
    "parse_unit", "pass_constprop", "pass_copyprop", "pass_intrinsics", "pass_jumps", "pass_kernels",
    "pass_licm", "pass_ssy", "passes", "postdominators", "print_stats", "reg_of", "register_pass",
    "remove_dead", "render_unit",
]
