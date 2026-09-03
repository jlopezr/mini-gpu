; fpga_smoke_test.asm
;
; Comprueba:
; - MOVI
; - ADD
; - STORE
; - LOAD
; - HALT
;
; CPU y monitor comparten el mismo mapa global.

    MOVI  R1, 10
    MOVI  R2, 20
    ADD   R3, R1, R2       ; R3 = 30

    MOVHI R4, 0x0010
    ADDI  R4, R4, 16       ; 0x00100010
    STORE R3, R4, 0        ; data[16] = 30
    LOAD  R5, R4, 0        ; R5 = data[16]

    HALT
