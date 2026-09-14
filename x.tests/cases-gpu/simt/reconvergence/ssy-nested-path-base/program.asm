; Una REGION interior abierta con un PATH exterior pendiente no debe consumir ese camino.

        GETTID R1
        MOVI   R2, 4
        SSY    outer_join

        BGE    R1, R2, outer_taken

outer_fallthrough:
        MOVI   R3, 2
        SSY    inner_join
        BGE    R1, R3, inner_taken

        MOVI   R4, 10
        BRA    inner_join

inner_taken:
        MOVI   R4, 20
        BRA    inner_join

inner_join:
        MOVI   R5, 30
        BRA    outer_join

outer_taken:
        MOVI   R5, 40
        BRA    outer_join

outer_join:
        EXIT
