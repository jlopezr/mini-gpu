"""Codon no tiene el módulo `struct`.

Síntoma (0.20.5): `no module named 'struct'`.
Rodeo: `tools/codon_compat.codon` implementa `read_u32`/`write_u32` con desplazamientos;
`tools/codon_compat.py` sigue usando struct (rápido en CPython).
Al resolverse: borrar esas dos funciones de `codon_compat.codon`.
"""
import struct
memory = bytearray(8)
struct.pack_into("<I", memory, 4, 0x01020304)
print("OK" if struct.unpack_from("<I", memory, 4)[0] == 0x01020304 else "MAL")
