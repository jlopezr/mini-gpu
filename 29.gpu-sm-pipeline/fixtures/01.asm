GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BLT R1, R2, low
MOVI R3, 30
BRA join
low:
MOVI R2, 2
SSY inner
BLT R1, R2, lowest
MOVI R3, 20
BRA inner
lowest:
MOVI R3, 10
inner:
ADDI R3, R3, 1
join:
ADDI R3, R3, 1
BAR
EXIT
