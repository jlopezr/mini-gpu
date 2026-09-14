; Reejecutar el SSY superior con un PATH pendiente reutiliza la REGION sin perder el pendiente.

        GETTID R1
        MOVI   R2, 4

loop:
        SSY    join
        BGE    R1, R2, path_b

        ADDI   R3, R3, 1
        BGE    R3, R2, join
        BRA    loop

path_b:
        MOVI   R4, 99
        BRA    join

join:
        EXIT
