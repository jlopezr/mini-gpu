; BLTU/BGEU comparan sin signo y BLT/BGE con signo. Con Ra = 0xFFFFFFFF y
; Rb = 1 las dos familias dan resultados OPUESTOS, asi que cada rama solo
; puede tomarse si su variante esta bien implementada.
;
;   unsigned: 4294967295 < 1  -> falso ; 4294967295 >= 1 -> cierto
;   signed:           -1 < 1  -> cierto;          -1 >= 1 -> falso

        MOVI R1, -1             ; 0xFFFFFFFF
        MOVI R2, 1
        MOVI R3, 0
        MOVI R4, 0

        BLTU R1, R2, skip_bltu  ; sin signo: NO salta
        ADDI R3, R3, 1          ; se ejecuta => R3 = 1
skip_bltu:

        BLT  R1, R2, skip_blt   ; con signo: SI salta
        ADDI R3, R3, 10         ; no se ejecuta
skip_blt:

        BGEU R1, R2, skip_bgeu  ; sin signo: SI salta
        ADDI R4, R4, 100        ; no se ejecuta
skip_bgeu:

        BGE  R1, R2, skip_bge   ; con signo: NO salta
        ADDI R4, R4, 1          ; se ejecuta => R4 = 1
skip_bge:

        HALT
