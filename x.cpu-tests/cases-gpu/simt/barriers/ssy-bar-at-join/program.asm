; BAR situada exactamente en el join.
; La normalizacion consume el PATH pendiente antes del siguiente fetch, de
; modo que BAR se ejecuta ya reconvergida (active_mask == live_mask) y no
; con la mascara parcial del primer camino que alcanza ese PC.

        GETTID R1
        MOVI   R2, 4

        SSY    join
        BGE    R1, R2, path_b

        MOVI   R3, 11
        BRA    join

path_b:
        MOVI   R3, 22
        BRA    join

join:
        BAR
        EXIT
