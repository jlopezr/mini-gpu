; REMU entre cero para con ERROR_DIVISION_BY_ZERO, tambien en la GPU.
        MOVI  R1, 7
        MOVI  R2, 0
        REMU  R3, R1, R2
        HALT
