"""Comprueba que un kernel cabe en la pila de su lane

Cada lane tiene `GPU_STACK_PER_LANE` bytes de `__gpu_stack`, y el pase `kernels` deja R30 a `HOME_AREA` bytes de su
final (el hueco de R1..R4 que lcc usa al entrar, que en un kernel no tiene llamador). Con las funciones expandidas
por `kernelcalls`, los marcos se apilan dentro del kernel; si se pasan, una lane escribe en la pila de la siguiente
y el resultado es incorrecto sin ningun aviso. Respecto al R30 de entrada, la pila de la lane va de
-(GPU_STACK_PER_LANE - HOME_AREA) a HOME_AREA:

  - R30 no puede bajar del principio (`frame_offsets`): ahi empiezan los marcos, y lo de una variable local cuya
    direccion se toma esta en el suyo;
  - cada `LOAD`/`STORE` con base R30 tiene que caer dentro (`stack_positions`, si se puede seguir la pila).

Si no se sabe cuanto vale R30 (dos caminos llegan con valores distintos), no se comprueba: `stats` lo cuenta en
`lanestack.unknown`. Va al final, cuando los marcos ya son los definitivos."""
from __future__ import annotations

from ..flow import build_cfg
from ..model import OptError, Unit
from ..registry import register_pass
from .kernels import GPU_STACK_PER_LANE, HOME_AREA, KERNEL_PREFIX
from .stackslots import WIDTH, frame_offsets, stack_positions

BOTTOM = -(GPU_STACK_PER_LANE - HOME_AREA)


@register_pass("lanestack", "error si un kernel se sale de la pila de su lane (marcos de funciones expandidas)")
def pass_lanestack(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if not function.name.startswith(KERNEL_PREFIX):
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        where = f"{unit.path}: {function.name}"
        levels = frame_offsets(blocks)
        if levels is None:
            stats["lanestack.unknown"] = stats.get("lanestack.unknown", 0) + 1
            continue
        lowest = min(levels.values(), default=0)
        if lowest < BOTTOM:
            raise OptError(f"{where}: los marcos llegan a {-lowest} bytes de pila y cada lane tiene "
                           f"{-BOTTOM} ({GPU_STACK_PER_LANE} menos {HOME_AREA} del hueco de R1..R4): "
                           "demasiadas funciones expandidas una dentro de otra, o locales demasiado grandes")
        positions = stack_positions(blocks) or {}
        lines = {id(line): line for block in blocks for line in block.lines}
        for key, start in positions.items():
            end = start + WIDTH[lines[key].op]
            if start < BOTTOM or end > HOME_AREA:
                raise OptError(f"{where}: {lines[key].render()} cae fuera de la pila de la lane "
                               f"({start} a {end} respecto a la entrada; cabe de {BOTTOM} a {HOME_AREA})")
