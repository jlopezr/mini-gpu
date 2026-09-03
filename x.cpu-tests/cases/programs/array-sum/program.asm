; Suma cinco palabras de data[0x300] y guarda el resultado en data[0x340].
    MOVI R1, 0x300
    MOVI R2, 5
    MOVI R3, 0
    MOVI R4, 1
loop:
    LOAD R5, R1, 0
    ADD  R3, R3, R5
    ADDI R1, R1, 4
    SUB  R2, R2, R4
    BNE  R2, R0, loop
    MOVI R6, 0x340
    STORE R3, R6, 0
    HALT
