; Push de REGION con la pila llena.
; Con simt_region_depth = 1, el segundo SSY esta en otro PC, luego no es
; reutilizacion y necesita push: debe dar ERROR_SIMT sin commit parcial.

        GETTID R1

        SSY    outer_join             ; region_count = 1
        SSY    inner_join             ; push con la pila llena: ERROR_SIMT

        NOP

inner_join:
        BRA    outer_join

outer_join:
        EXIT
