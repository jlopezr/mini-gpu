; fpga_smoke_test.asm
;
; Comprueba:
; - MOVI
; - ADD
; - STORE
; - LOAD
; - HALT
;
; La CPU ve su memoria de datos desde 0x00000000.
; El monitor ve esa misma memoria desde 0x00100000.

    MOVI  R1, 10
    MOVI  R2, 20
    ADD   R3, R1, R2       ; R3 = 30

    MOVI  R4, 16           ; dirección local de datos
    STORE R3, R4, 0        ; data[16] = 30
    LOAD  R5, R4, 0        ; R5 = data[16]

    HALT
