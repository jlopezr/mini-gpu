GETTID R1
ANDI R1, R1, 7
loop:
SSY done
BEQ R1, R0, handler
ADDI R1, R1, -1
BRA loop
handler:
ADDI R3, R3, 10
BRA done
done:
ADDI R3, R3, 1
EXIT
