"""`from __future__ import annotations` no se admite.

Los dos simuladores lo llevan en la cabecera. Síntoma (0.20.5): `no module named
'__future__'`.
Rodeo: el núcleo compartido no lo usa. Sin él, PyPy 3.11 evalúa las anotaciones al
definir la función: no puede haber referencias adelantadas (l07) y las uniones van
como `int | None` (válido desde 3.10).
Al resolverse: se puede volver a poner.
"""
from __future__ import annotations
def f(x: int | None = None) -> int:
    return 0 if x is None else x
print("OK" if f(2) == 2 else "MAL")
