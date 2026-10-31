"""`@dataclass(frozen=True)` no se admite.

Síntoma (0.20.5): `class decorator got unexpected argument`.
Rodeo: `@dataclass` sin `frozen` en `Fault`, `SimtRegion` y `SimtPath` de
`11.gpu-sim-func/minigpu_sim.py`: el simulador nunca los modificaba.
Al resolverse: volver a `@dataclass(frozen=True)`.
"""
@dataclass(frozen=True)
class Region:
    pc: int
print("OK" if Region(4).pc == 4 else "MAL")
