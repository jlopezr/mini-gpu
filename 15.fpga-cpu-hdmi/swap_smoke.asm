; ============================================================
; swap_smoke.asm - comprobacion minima del doble buffer desde la CPU
;
; No dibuja nada. Ejercita el camino completo CPU -> registros de video:
; leer FB_FRONT y FB_BACK, pedir un intercambio, esperar a que el hardware lo
; aplique al empezar el frame siguiente, y comprobar que FB_FRONT pasa a valer
; lo que valia FB_BACK.
;
; Es el programa que corre `cpu_video_tb.v`, y es corto a proposito: la version
; larga (`swap_demo.asm`) escribe 38400 palabras por frame, que en simulacion
; no termina en un tiempo razonable.
;
; Al terminar:
;   R1 = FB_FRONT antes del intercambio
;   R2 = FB_BACK  antes del intercambio
;   R3 = FB_FRONT despues; tiene que ser igual a R2
;   R4 = FB_BACK  despues; tiene que ser igual a R1
; ============================================================

start:
    MOVHI R20, 0x8000          ; registros de video en 0x80000000
    LOAD  R1, R20, 0           ; FB_FRONT
    LOAD  R2, R20, 4           ; FB_BACK

    MOVI  R7, 1
    MOVI  R9, 0
    STORE R7, R20, 8           ; SWAP = 1

wait_swap:
    LOAD  R8, R20, 8           ; bit 0: intercambio pendiente
    BNE   R8, R9, wait_swap

    LOAD  R3, R20, 0           ; FB_FRONT tras el intercambio
    LOAD  R4, R20, 4           ; FB_BACK tras el intercambio
    HALT
