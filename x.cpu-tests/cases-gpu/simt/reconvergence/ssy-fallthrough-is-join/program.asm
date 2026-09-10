; Caso especial PC+4 == join: la mascara fall-through se aparca sin crear PATH.

        GETTID R1
        MOVI   R2, 4

        SSY    join
        BGE    R1, R2, taken

join:
        EXIT

taken:
        MOVI   R3, 77
        BRA    join
