; BNE: salta si Ra != Rb (R1 = tid - 4, comparado con R0 = 0).
GETTID R1
ANDI R1, R1, 7
ADDI R1, R1, -4
SSY join
BNE R1, R0, taken
MOVI R3, 3
BRA join
taken:
MOVI R3, 7
join:
HALT
