; EXIT ejecutado desde un PATH ya seleccionado.
; Las lanes que terminan dentro del PATH salen de live_mask y no deben
; reaparecer cuando despues se cierre la REGION.

        GETTID R1
        MOVI   R2, 4

        SSY    join
        BGE    R1, R2, pending        ; fall-through 0x0F, PATH 0xF0

        MOVI   R3, 11
        BRA    join

pending:
        MOVI   R3, 22
        EXIT                          ; mueren las lanes 4..7 dentro del PATH

join:
        EXIT
