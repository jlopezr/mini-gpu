; ============================================================
; band.asm - una banda verde fija sobre fondo azul, con doble buffer
;
; Es el programa mas simple que ejercita la cadena grafica entera: escribe el
; framebuffer trasero, pide el intercambio y espera a que ocurra, en bucle. Y
; es DETERMINISTA a proposito: la banda NO se mueve entre frames.
;
; Eso ultimo es la decision que hace el caso util. Las demos de la 16 mueven la
; banda, asi que el frame esperado dependeria de cuantos intercambios hayan
; pasado, y el fichero de referencia habria que regenerarlo cada vez que se
; tocara el numero de swap en el que se para. Con la banda fija, cualquier
; frame a partir del segundo es el mismo, y el caso puede parar donde quiera.
;
; Los dos primeros frames siguen siendo especiales -- los dos buffers arrancan
; con basura -- asi que el caso para en el intercambio 3 o mas.
;
; Registros de video, en 0x80000000:
;   +0 FB_FRONT  +4 FB_BACK  +8 SWAP  +12 STATUS  +16 SWAP_COUNT  +20 HALT_AT
;
; Convencion de registros:
;   R1  base del buffer trasero     R2  contador de lineas
;   R3  contador de palabras        R4  direccion de la linea
;   R5  temporal                    R6  puntero de escritura
;   R7  constante 1                 R8  lectura de SWAP
;   R0  cero, cableado por la ISA    R13 color de la linea actual
;   R14 constante 9                 R15 constante 7
;   R20 base de los registros       R22 lineas totales (240)
;   R23 color de fondo              R24 color de la banda
;   R25 palabras por linea (160)    R26 primera linea de la banda (96)
;   R27 primera linea despues (112)
; ============================================================

.include "mmio.inc"

start:
    LI    R20, MMIO_VIDEO_BASE          ; registros de video

    MOVHI R23, 0x001F
    ORI   R23, R23, 0x001F     ; azul en las dos mitades de la palabra
    MOVHI R24, 0x07E0
    ORI   R24, R24, 0x07E0     ; verde

    MOVI  R25, 160             ; palabras por linea (320 px de 16 bits)
    MOVI  R22, 240             ; lineas
    MOVI  R26, 96              ; primera linea de la banda
    MOVI  R27, 112             ; primera linea despues de la banda
    MOVI  R14, 9               ; desplazamientos para *640
    MOVI  R15, 7
    MOVI  R7, 1
frame:
    LOAD  R1, R20, MMIO_VIDEO_FB_BACK_OFF           ; R1 = FB_BACK, cambia en cada intercambio
    ADDI  R4, R1, 0            ; direccion de la linea 0
    MOVI  R2, 0

draw_line:
    ; Color de esta linea: verde dentro de la banda, azul fuera.
    ADDI  R13, R23, 0
    BLT   R2, R26, line_ready
    BGE   R2, R27, line_ready
    ADDI  R13, R24, 0

line_ready:
    MOVI  R3, 0
    ADDI  R6, R4, 0
draw_word:
    STORE R13, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, draw_word

    ADDI  R4, R4, 640
    ADDI  R2, R2, 1
    BLT   R2, R22, draw_line

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF
    BNE   R8, R0, wait_swap

    BRA   frame
