"""Una anotación no puede nombrar una clase definida más abajo.

Python lo admite desde 3.14 (anotaciones diferidas) o con `from __future__ import
annotations`, que Codon tampoco acepta (l15). Síntoma (0.20.5): `name 'Lane' is
not defined`. La parte Python de este caso necesita 3.14 o posterior.
Rodeo: ordenar las clases (la lane de minigpu_sim.py antes que `Warp`) o quitar
la anotación.
Al resolverse: se puede volver al orden natural (de arriba abajo).
"""
class Warp:
    def __init__(self):
        self.lanes = [Lane(i) for i in range(2)]
    def first(self, lane: Lane) -> int:
        return lane.n
class Lane:
    def __init__(self, n: int):
        self.n = n
print("OK" if Warp().first(Lane(3)) == 3 else "MAL")
