"""Codon no tiene `int.from_bytes` ni `int.to_bytes`.

Síntoma (0.20.5): `'int' object has no attribute 'from_bytes'`.
Rodeo: `read_bytes`/`write_bytes` de `tools/codon_compat` (accesos de 1 y 2 bytes).
Al resolverse: borrar esas dos funciones de `codon_compat.codon`.
"""
memory = bytearray(4)
memory[1:3] = (0x0201).to_bytes(2, "little")
print("OK" if int.from_bytes(memory[1:3], "little") == 0x0201 else "MAL")
