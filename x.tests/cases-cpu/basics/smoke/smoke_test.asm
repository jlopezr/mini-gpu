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
    ADDI  R4, R4, 0x0100  ; 0x00100100
    STORE R3, R4, 0        ; data[256] = 30
    LOAD  R5, R4, 0        ; R5 = data[256]

    ; Marca binaria sencilla para probar la comparación de dumps.
    MOVI  R6, 0x0a41       ; bytes 41 0a: texto "A" y salto de línea
    MOVHI R7, 0x0010
    ADDI  R7, R7, 0x0200  ; 0x00100200
    STORE R6, R7, 0        ; data[512] comienza por el dump esperado

    HALT
