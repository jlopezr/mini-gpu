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

    ; Elegir donde vive el framebuffer. Tras el reset las dos bases valen
    ; cero --el framebuffer es una decision del programa, no una reserva
    ; que el hardware impone-- asi que heredarlas seria dibujar sobre el
    ; propio programa. La direccion es la de siempre; lo que cambia es que
    ; ahora hay que escribirla.
    MOVHI R30, 0x0100
    STORE R30, R20, 0          ; FB_FRONT
    MOVHI R30, 0x0102
    ORI   R30, R30, 0x5800
    STORE R30, R20, 4          ; FB_BACK, un frame mas arriba

    ; Encender el scanout. Tras el reset el modo es PATTERN --la memoria
    ; recien encendida contiene basura, asi que arrancar leyendola daria
    ; una salida indefinida-- y un programa que dibuja tiene que pedir
    ; que se vea lo que dibuja. Ver video_registers.v, VIDEO_CTRL.
    MOVI  R30, 2               ; SCANOUT
    STORE R30, R20, 24         ; VIDEO_CTRL
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
