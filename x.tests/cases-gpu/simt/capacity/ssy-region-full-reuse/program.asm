; Un SSY ya en el top se reutiliza sin push, por lo que no depende del espacio libre en REGION.

        GETTID R1
        MOVI   R2, 0
        MOVI   R3, 3

loop:
        SSY    join
        BGE    R2, R3, join
        ADDI   R2, R2, 1
        BRA    loop

join:
        EXIT
