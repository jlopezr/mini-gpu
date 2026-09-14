; Dos SSY distintos que apuntan al mismo join deben crear dos REGION distintas.

        GETTID R1

        SSY    join
        MOVI   R2, 8
        BGE    R1, R2, join

        SSY    join
        MOVI   R3, 8
        BGE    R1, R3, join

join:
        EXIT
