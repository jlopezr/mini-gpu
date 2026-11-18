; ============================================================
; start-invalid.asm - START con una configuracion invalida da error
;
; WIDTH = 8 no es multiplo de 16 (mmio.md §11.1): la escritura en CTRL falla y
; la CPU para con ERROR_MEMORY_ACCESS (0x02) en ese STORE. Antes, una
; configuracion valida en el otro canal prueba que el error no es del bloque.
;
; Registros al parar:
;   R1  STATUS del canal 0 tras el FILL valido (DONE = 2)
;   R2  STATUS del canal 1 antes del START invalido: 0, tras limpiar DONE y
;       ERROR (el motor no se reinicia al cargar un programa, asi que puede
;       quedar el DONE de un programa anterior)
; ============================================================

.include "mmio.inc"

.equ DMA_DST,        0x04
.equ DMA_WIDTH,      0x08
.equ DMA_HEIGHT,     0x0C
.equ DMA_DST_STRIDE, 0x14
.equ DMA_PATTERN,    0x18
.equ DMA_CTRL,       0x1C
.equ DMA_STATUS,     0x20
.equ DMA_CH1,        0x40

start:
    LI    R20, MMIO_DMA_BASE

    ; Canal 0: un FILL valido de 16 bytes.
    MOVHI R7, 0x0013
    STORE R7, R20, DMA_DST
    MOVI  R7, 16
    STORE R7, R20, DMA_WIDTH
    MOVI  R7, 1
    STORE R7, R20, DMA_HEIGHT
    MOVI  R7, 16
    STORE R7, R20, DMA_DST_STRIDE
    MOVI  R7, 3
    STORE R7, R20, DMA_CTRL
wait0:
    LOAD  R1, R20, DMA_STATUS
    ANDI  R7, R1, 6
    BEQ   R7, R0, wait0

    ; Canal 1: WIDTH = 8, invalido.
    MOVHI R7, 0x0013
    ORI   R7, R7, 0x1000
    STORE R7, R20, DMA_CH1+DMA_DST
    MOVI  R7, 8
    STORE R7, R20, DMA_CH1+DMA_WIDTH
    MOVI  R7, 1
    STORE R7, R20, DMA_CH1+DMA_HEIGHT
    MOVI  R7, 16
    STORE R7, R20, DMA_CH1+DMA_DST_STRIDE
    MOVI  R7, 6
    STORE R7, R20, DMA_CH1+DMA_STATUS ; W1C de DONE y ERROR
    LOAD  R2, R20, DMA_CH1+DMA_STATUS
    MOVI  R7, 3
    STORE R7, R20, DMA_CH1+DMA_CTRL   ; aqui para, error 0x02
    MOVI  R3, 1                       ; no se ejecuta: el PC del error lo dice
    HALT
