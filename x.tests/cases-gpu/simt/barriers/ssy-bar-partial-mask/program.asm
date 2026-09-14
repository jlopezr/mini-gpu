; BAR alcanzada antes del join con mascara parcial.
; El fall-through llega a BAR con active_mask = 0x0F y live_mask = 0xFF.
; El simulador exige que participen todas las lanes vivas, de modo que la
; barrera debe producir ERROR_BARRIER.

        GETTID R1
        MOVI   R2, 4

        SSY    join
        BGE    R1, R2, path_b

        BAR                           ; active_mask 0x0F != live_mask 0xFF
        MOVI   R3, 11
        BRA    join

path_b:
        MOVI   R3, 22
        BRA    join

join:
        EXIT
