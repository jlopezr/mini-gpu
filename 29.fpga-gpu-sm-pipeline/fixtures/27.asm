GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY outer
BLT R1, R2, low
SSY inner
EXIT
inner:
MOVI R3, 99
BRA outer
low:
MOVI R3, 10
outer:
ADDI R3, R3, 1
EXIT
