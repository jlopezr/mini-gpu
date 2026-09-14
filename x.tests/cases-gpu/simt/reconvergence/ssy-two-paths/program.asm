; Dos divergencias dentro de una unica REGION antes de alcanzar el join.

        GETTID R1
        SSY    join

        MOVI   R2, 6
        BGE    R1, R2, path_hi

        MOVI   R2, 3
        BGE    R1, R2, path_mid

        MOVI   R3, 10
        BRA    join

path_mid:
        MOVI   R3, 20
        BRA    join

path_hi:
        MOVI   R3, 30
        BRA    join

join:
        EXIT
