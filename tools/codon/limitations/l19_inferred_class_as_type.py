"""Una clase con los campos inferidos (desde `__init__`) es genérica: no se puede
heredar de ella ni usarla como tipo de un campo declarado.

Síntomas (0.20.5): `cannot realize Base.0[...]` (aserción interna del compilador)
al heredar; `type of attribute 'bus' ... cannot be inferred` al declarar
`bus: MmioBus`.
Rodeo: declarar los campos de esas clases: `CPU` (minicpu_core, base de
`_SystemCpu`), `System` y `StreamingMultiprocessor` (minigpu_core), `_Port` y
`MmioBus` (cpu_gpu_core). Y, donde no hace falta heredar, sacar las constantes de
clase al módulo para que la clase siga infiriendo (los dispositivos de control).
Al resolverse: las declaraciones pueden quedarse.
"""
class Base:
    def __init__(self, n: int):
        self.n = n
class Sub(Base):
    def __init__(self, n: int):
        super().__init__(n)
print("OK" if Sub(3).n == 3 else "MAL")
