; EXIT del camino activo con PATH pendientes: la normalizacion sigue con el pendiente.

        GETTID R1
        MOVI   R2, 4
        SSY    join

        BGE    R1, R2, pending

        EXIT

pending:
        MOVI   R3, 99
        BRA    join

join:
        EXIT
