; Multiplica 13 por 11 mediante sumas y desplazamientos: resultado 143.
    MOVI R1, 13
    MOVI R2, 11
    MOVI R3, 0
    MOVI R4, 1
loop:
    AND  R5, R2, R4
    BEQ  R5, R0, skip_add
    ADD  R3, R3, R1
skip_add:
    SHL  R1, R1, R4
    SHR  R2, R2, R4
    BNE  R2, R0, loop
    HALT
