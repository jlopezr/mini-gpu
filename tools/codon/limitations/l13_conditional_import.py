"""Los imports se resuelven al compilar: `try/except ImportError` no los evita.

Síntoma (0.20.5): `no module named 'dataclasses'`, aunque esté dentro del `try`.
Rodeo: un módulo `X.py` (Python) con un gemelo `X.codon` al lado: Codon prefiere
el `.codon`. Es `tools/codon_compat`.
Al resolverse: no cambia nada por sí solo; ver l01-l03.
"""
try:
    from dataclasses import dataclass
except ImportError:
    pass
@dataclass
class Point:
    x: int
print("OK" if Point(2).x == 2 else "MAL")
