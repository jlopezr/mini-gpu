; PATH llena pero divergencia que no necesita push.
; Con simt_path_depth = 2 las dos primeras divergencias llenan la pila.
; La tercera manda el camino tomado directamente al join, asi que esas
; lanes se aparcan sin reservar PATH y la operacion debe estar permitida.

        GETTID R1
        SSY    join

        MOVI   R2, 6
        BGE    R1, R2, path_hi        ; PATH #1 = lanes 6..7

        MOVI   R2, 4
        BGE    R1, R2, path_mid       ; PATH #2 = lanes 4..5 (pila llena)

        MOVI   R2, 2
        BGE    R1, R2, join           ; lanes 2..3 al join: sin push

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
