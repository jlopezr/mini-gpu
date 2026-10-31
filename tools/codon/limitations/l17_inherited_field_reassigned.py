"""Una subclase no puede reasignar en su `__init__` un campo heredado.

Codon toma `self.memory = memory` en el `__init__` de la subclase por la
declaración de un campo nuevo. Síntoma (0.20.5): `field 'memory' already defined`.
Rodeo: declarar en la subclase sus propios campos (`bus: MmioBus`); con campos
declarados Codon deja de inferir y la asignación es al campo heredado. Lo llevan
`_GpuSystem` y `_SystemCpu` de cpu_gpu_core.py.
Al resolverse: las declaraciones pueden quedarse.
"""
class Base:
    memory: bytearray
    def __init__(self):
        self.memory = bytearray(4)
class Shared(Base):
    def __init__(self, memory: bytearray):
        super().__init__()
        self.memory = memory
        self.bus = 1
print("OK" if len(Shared(bytearray(8)).memory) == 8 else "MAL")
