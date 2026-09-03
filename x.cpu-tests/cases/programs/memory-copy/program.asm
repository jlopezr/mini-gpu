; Copia seis palabras de data[0x400] a data[0x500].
    MOVI R1, 0x400
    MOVI R2, 0x500
    MOVI R3, 6
    MOVI R4, 1
loop:
    LOAD  R5, R1, 0
    STORE R5, R2, 0
    ADDI  R1, R1, 4
    ADDI  R2, R2, 4
    SUB   R3, R3, R4
    BNE   R3, R0, loop
    LOAD  R6, R2, -4
    HALT
