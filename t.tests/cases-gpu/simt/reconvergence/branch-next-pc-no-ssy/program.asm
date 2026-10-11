; Salto cuyo destino es PC+4 sin SSY: no hay divergencia y no se abre estado SIMT.
GETTID R1
ANDI R1, R1, 7
BEQ R1, R0, next
next: ADDI R3, R3, 1
EXIT
