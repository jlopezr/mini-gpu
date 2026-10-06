; Cada hilo vuelca las cinco identidades de la familia GETID: cinco palabras
; seguidas en 4096 + 20 * tid.
    GETTID   R1
    GETLANE  R2
    GETWARP  R3
    GETLWARP R4
    GETARG   R5
    MOVI     R6, 20
    MUL      R7, R1, R6
    ADDI     R7, R7, 4096
    STORE    R1, R7, 0
    STORE    R2, R7, 4
    STORE    R3, R7, 8
    STORE    R4, R7, 12
    STORE    R5, R7, 16
    HALT
