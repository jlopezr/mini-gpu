"""Lo que Codon no trae y los núcleos de los simuladores necesitan.

Este fichero es el de Python: usa la biblioteca estándar, sin coste. Al lado está
`codon_compat.codon`, su gemelo para Codon, que prefiere `X.codon` a `X.py` al
importar (Python no lo ve). Así el núcleo de cada simulador es el mismo fichero
en los dos lenguajes.

Cada nombre es un rodeo de una limitación de `tools/codon/LIMITACIONES.md`
(entre paréntesis). Cuando Codon la resuelva, se borra de aquí y del gemelo, y
los núcleos vuelven a usar la biblioteca estándar directamente.
"""
import struct
from dataclasses import dataclass  # noqa: F401 - se reexporta (l03)


def load_u32(memory: bytearray, address: int) -> int:
    """Palabra little-endian de `memory` (l01: sin `struct`). Sin comprobar rango."""
    return struct.unpack_from("<I", memory, address)[0]


def store_u32(memory: bytearray, address: int, value: int) -> None:
    """Escribe una palabra little-endian; `value` ya en 32 bits (l01)."""
    struct.pack_into("<I", memory, address, value)


def load_le(memory: bytearray, address: int, size: int) -> int:
    """`size` bytes little-endian (l02: sin `int.from_bytes`)."""
    return int.from_bytes(memory[address:address + size], "little")


def store_le(memory: bytearray, address: int, size: int, value: int) -> None:
    """Los `size` bytes bajos de `value`, little-endian (l02: sin `int.to_bytes`)."""
    memory[address:address + size] = value.to_bytes(size, "little")
