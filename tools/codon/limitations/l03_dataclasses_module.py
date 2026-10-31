"""Codon trae `@dataclass` incorporado, pero no el módulo `dataclasses`.

Python necesita el import y Codon lo rechaza; `try/except ImportError` tampoco
sirve (ver l13). Síntoma (0.20.5): `no module named 'dataclasses'`.
Rodeo: `from tools.codon_compat import dataclass`: la de verdad en Python y la
identidad en Codon (las clases con campos declarados ya tienen `__init__`).
Al resolverse: importar `dataclass` de `dataclasses` directamente.
"""
from dataclasses import dataclass
@dataclass
class Fault:
    code: int
    pc: int = 0
print("OK" if Fault(3).code + Fault(1, 2).pc == 5 else "MAL")
