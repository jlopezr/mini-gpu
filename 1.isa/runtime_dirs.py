"""Donde estan las cabeceras y los fuentes compartidos: la unica definicion de esas rutas.

    runtime/include/   lo que se incluye y no emite nada: cabeceras de C y `mmio.inc` (solo `.equ`)
    runtime/src/       codigo: el arranque, el runtime de la GPU y las rutinas en ensamblador

El ensamblador busca en las dos (`ASM_INCLUDE_DIRS`): un `.asm` hace `.include "drawline.inc"` o
`.include "mmio.inc"` por su nombre. El compilador de C solo en `include/` (`C_INCLUDE_DIRS`).
`1.isa` ya esta en el `sys.path` de todo el que importa `mini_asm`, asi que basta `from runtime_dirs import ...`.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
INCLUDE = RUNTIME / "include"
SRC = RUNTIME / "src"

ASM_INCLUDE_DIRS = (INCLUDE, SRC)
C_INCLUDE_DIRS = (INCLUDE,)
