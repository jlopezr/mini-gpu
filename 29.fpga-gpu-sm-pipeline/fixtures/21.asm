GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY outer
BLT R1, R2, low
MOVI R2, 6
SSY inner
BLT R1, R2, middle
MOVI R3, 30
BRA inner
middle:
MOVI R3, 20
inner:
ADDI R3, R3, 1
BRA outer
low:
MOVI R3, 10
outer:
ADDI R3, R3, 1
BAR
EXIT
