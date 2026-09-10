GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY first
BLT R1, R2, first
ADDI R3, R3, 10
first:
SSY second
BGE R1, R2, second
ADDI R3, R3, 20
second:
ADDI R3, R3, 1
EXIT
