; Grupo 0 (pc 0)
        MOVI   R5, 4096
        BAR
        MOVI   R3, 7
        STORE  R3, R5, 0
        EXIT

; Grupo 1 (pc 20): espera la bandera del grupo 0 antes de su propia BAR
        MOVI   R5, 4096
wait:
        LOAD   R6, R5, 0
        BEQ    R6, R0, wait
        BAR
        MOVI   R4, 9
        EXIT
