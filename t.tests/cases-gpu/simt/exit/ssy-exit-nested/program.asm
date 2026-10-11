; EXIT dentro de una REGION interior y filtrado por live_mask al restaurar mascaras.

        GETTID R1
        MOVI   R2, 4

        SSY    outer_join
        BGE    R1, R2, outer_b

        MOVI   R3, 2
        SSY    inner_join
        BGE    R1, R3, inner_b

        EXIT

inner_b:
        MOVI   R4, 44
        BRA    inner_join

inner_join:
        BRA    outer_join

outer_b:
        MOVI   R4, 88
        BRA    outer_join

outer_join:
        EXIT
