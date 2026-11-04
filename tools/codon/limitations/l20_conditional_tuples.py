"""`A if c else B` con dos tuplas de distinta longitud no tiene tipo.

En Codon la longitud es parte del tipo de una tupla. Síntoma (0.20.5):
`'Tuple[int,int,int]' does not match expected type 'Tuple[int,int,int,int]'`.
Rodeo: `x in A if c else x in B` (GpuCoreDevice.validate).
Al resolverse: volver a `x in (A if c else B)`.
"""
READ = (1, 2, 3, 4)
WRITE = (5, 6, 7)
def allowed(offset: int, writing: bool) -> bool:
    return offset in (WRITE if writing else READ)
print("OK" if allowed(6, True) and not allowed(6, False) else "MAL")
