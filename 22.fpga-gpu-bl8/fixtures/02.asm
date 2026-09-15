GETTID R1
ANDI R1, R1, 7
loop:
SSY done
BEQ R1, R0, done
ADDI R1, R1, -1
ADDI R3, R3, 1
BRA loop
done:
BAR
EXIT
