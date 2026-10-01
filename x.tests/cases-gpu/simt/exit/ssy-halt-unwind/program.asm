; HALT con dos REGION abiertas: se deshacen las dos y nada posterior se ejecuta.
SSY outer
SSY inner
HALT
NOP
inner:
NOP
NOP
outer:
MOVI R3, 99
HALT
