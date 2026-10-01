; Suma cinco palabras desde 0x00100300 y guarda en 0x00100340.
    MOVHI R1, 0x0010
    ADDI  R1, R1, 0x0300
    MOVI R2, 5
    MOVI R3, 0
    MOVI R4, 1
loop:
    LOAD R5, R1, 0
    ADD  R3, R3, R5
    ADDI R1, R1, 4
    SUB  R2, R2, R4
    BNE  R2, R0, loop
    MOVHI R6, 0x0010
    ADDI  R6, R6, 0x0340
    STORE R3, R6, 0
    HALT
