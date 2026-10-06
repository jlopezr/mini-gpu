; STOREB, STOREH, LOADB, LOADUB, LOADH y LOADUH de 64 hilos (8 warps de 8 lanes).
;
; Cuatro lanes consecutivas caen en la MISMA palabra, y cada una escribe solo su
; byte (o su mitad): si la mascara de bytes del RTL fuera de palabra entera, los
; vecinos se pisarian. Las barreras separan la escritura de la lectura cruzada,
; que lee lo que escribio el hilo opuesto (63 - tid), de otro warp.
;
; Mapa (todo dentro de 4096..6143):
;   0x1000  b[64]   bytes             0x1100  b sin signo, una palabra por hilo
;   0x1200  b con signo               0x1300  h[64]  medias palabras
;   0x1400  h sin signo               0x1500  h con signo
;   0x1600  la palabra de b que contiene el byte del hilo (LOAD tras los STOREB)
    GETTID  R1                  ; tid 0..63
    MOVI    R2, 4096            ; b
    ADD     R3, R2, R1          ; &b[tid]
    MOVI    R4, 5
    MUL     R5, R1, R4
    ADDI    R5, R5, 124         ; 5*tid + 0x7C: el bit 7 pasa a uno a mitad de camino
    STOREB  R5, R3, 0
    BAR

    ANDI    R28, R3, 65532      ; la palabra que contiene b[tid]
    LOAD    R29, R28, 0
    MOVI    R4, 4
    MUL     R12, R1, R4         ; 4 * tid
    MOVI    R30, 5632
    ADD     R30, R30, R12
    STORE   R29, R30, 0

    MOVI    R6, 63
    SUB     R7, R6, R1          ; 63 - tid
    ADD     R8, R2, R7          ; &b[63 - tid]
    LOADUB  R9, R8, 0
    LOADB   R10, R8, 0
    MOVI    R13, 4352
    ADD     R13, R13, R12
    STORE   R9, R13, 0
    MOVI    R14, 4608
    ADD     R14, R14, R12
    STORE   R10, R14, 0

    MOVI    R15, 2
    MUL     R16, R1, R15        ; 2 * tid
    MOVI    R17, 4864           ; h
    ADD     R18, R17, R16       ; &h[tid]
    MOVI    R19, 1105           ; 0x451
    MUL     R20, R1, R19
    ADDI    R20, R20, 32512     ; + 0x7F00: el bit 15 pasa a uno desde el hilo 1
    STOREH  R20, R18, 0
    BAR

    SUB     R21, R6, R1         ; 63 - tid
    MUL     R22, R21, R15       ; 2 * (63 - tid)
    ADD     R23, R17, R22       ; &h[63 - tid]
    LOADUH  R24, R23, 0
    LOADH   R25, R23, 0
    MOVI    R26, 5120
    ADD     R26, R26, R12
    STORE   R24, R26, 0
    MOVI    R27, 5376
    ADD     R27, R27, R12
    STORE   R25, R27, 0
    HALT
