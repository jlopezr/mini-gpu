GETTID R1
ANDI R1, R1, 7
ADDI R1, R1, -4
SSY join
BGE R1, R0, taken
MOVI R3, 3
BRA join
taken:
MOVI R3, 7
join:
HALT
