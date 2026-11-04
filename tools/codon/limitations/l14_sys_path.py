"""`sys.path` no existe en Codon.

Los simuladores hacen `sys.path.insert(0, raíz)` para importar `tools.*`.
Síntoma (0.20.5): `cannot import name 'path' from 'sys'` (también con --auto-python).
Rodeo: el núcleo vive en un módulo sin CLI ni `sys.path`; el backend Codon copia
las fuentes, sin cambiarlas, a un directorio con `tools/` al lado.
Al resolverse: el núcleo podría volver al mismo fichero que la CLI.
"""
import sys
sys.path.insert(0, ".")
print("OK" if sys.path[0] == "." else "MAL")
