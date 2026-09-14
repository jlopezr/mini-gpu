; Si el destino tomado coincide con PC+4 no hay divergencia arquitectonica.

        GETTID R1
        MOVI   R2, 4

        SSY    join
        BGE    R1, R2, next

next:
        MOVI   R3, 55
        BRA    join

join:
        EXIT
