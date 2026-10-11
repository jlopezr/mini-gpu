; Overflow atomico de la pila PATH.
; Con 8 lanes y simt_path_depth = 4, las cuatro primeras divergencias crean
; cuatro caminos pendientes y la quinta debe producir ERROR_SIMT sin llegar a
; hacer commit parcial (PC, active_mask y la pila quedan intactos).

        GETTID R1
        SSY    join

        MOVI   R2, 7
        BGE    R1, R2, path7          ; PATH count = 1

        MOVI   R2, 6
        BGE    R1, R2, path6          ; PATH count = 2

        MOVI   R2, 5
        BGE    R1, R2, path5          ; PATH count = 3

        MOVI   R2, 4
        BGE    R1, R2, path4          ; PATH count = 4 (pila llena)

        MOVI   R2, 3
        BGE    R1, R2, path3          ; quinto push: ERROR_SIMT

        BRA    join

path3:
        NOP
        BRA    join

path4:
        NOP
        BRA    join

path5:
        NOP
        BRA    join

path6:
        NOP
        BRA    join

path7:
        NOP
        BRA    join

join:
        EXIT
