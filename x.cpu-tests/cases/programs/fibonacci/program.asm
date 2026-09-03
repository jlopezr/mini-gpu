; Genera los diez primeros términos de Fibonacci en data[0x200].
    MOVI R1, 0
    MOVI R2, 1
    MOVI R3, 0x200
    MOVI R4, 10
    MOVI R5, 1
loop:
    STORE R1, R3, 0
    ADD   R6, R1, R2
    ADDI  R1, R2, 0
    ADDI  R2, R6, 0
    ADDI  R3, R3, 4
    SUB   R4, R4, R5
    BNE   R4, R0, loop
    HALT
