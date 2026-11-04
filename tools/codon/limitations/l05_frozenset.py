"""No existe `frozenset`.

Síntoma (0.20.5): `name 'frozenset' is not defined`.
Rodeo: `set` normal para las constantes (`LOAD_OPCODES` de minigpu_sim.py).
Al resolverse: volver a `frozenset`.
"""
LOADS = frozenset((0x15, 0x18))
print("OK" if 0x18 in LOADS else "MAL")
