; ============================================================
; render_v2.asm - el plasma de render.asm con las escrituras coalescidas
;
; Misma imagen byte a byte, misma aritmética, mismo mosaico de 80 x 60 celdas de
; 4 x 4 píxeles, mismo bucle de CPU. Cambia SOLO cómo se reparten las celdas
; entre las lanes, y con eso, cuántas transacciones de memoria hace la GPU.
;
;   mini-dbg --gpu examples\render\render_v2.asm --window
;
; ---- Por qué existe ----
;
; En render.asm el hilo `tid` pinta la fila de celdas `tid`. En un `STORE` las 8
; lanes de un warp escriben en 8 filas distintas, separadas 2 560 bytes: la LSU no
; puede juntarlas y cada lane es una transacción. Son 38 400 por frame, y a ~17
; ciclos cada una el frame es de la memoria, no del cálculo.
;
; Aquí un WARP entero pinta una fila de celdas y sus 8 lanes se reparten así:
;
;     lane l  ->  celda  cx = 4*j + (l >> 1)      (j = 0..19, la vuelta del bucle)
;                 palabra  l & 1 de esa celda
;
; Una celda son 2 palabras (8 bytes) por línea de píxeles, así que 4 celdas son 8
; palabras = 32 bytes seguidos, y un `STORE` de las 8 lanes escribe 32 bytes
; contiguos y alineados: **2 transacciones de 16 bytes** en vez de 8. 4 800 celdas
; x 4 líneas / 4 celdas por STORE x 2 = 9 600 transacciones por frame (un cuarto).
;
; Coste: las dos lanes de una celda calculan el mismo color, y el warp da 20 vueltas
; por fila de celdas en vez de 10. A cambio ya no hay divergencia ninguna: las 8
; lanes de un warp siempre tienen la misma fila, así que la condición del bucle de
; filas es uniforme y no hace falta SSY.
;
; El reparto de filas: el warp lógico `w` pinta las filas w, w+8, w+16... (60 filas
; entre 8 warps: los cuatro primeros hacen 8 filas y los otros cuatro, 7).
; ============================================================

.include "mmio.inc"

.equ FB_A,    0x01000000
.equ FB_B,    0x01025800            ; FB_A + 320*240*2
.equ NWARPS,  8
.equ CELLS_X, 80
.equ CELLS_Y, 60

; ---- CPU (la misma que en render.asm) ----
; R20 = base de VIDEO, R21 = número de frame. gpu_run destruye R1..R15 y R31.
start:
    LI    R20, MMIO_VIDEO_BASE
    LI    R30, FB_A
    STORE R30, R20, MMIO_VIDEO_FB_FRONT_OFF
    LI    R30, FB_B
    STORE R30, R20, MMIO_VIDEO_FB_BACK_OFF
    MOVI  R30, MMIO_VIDEO_MODE_SCANOUT
    STORE R30, R20, MMIO_VIDEO_CTRL_OFF

    LI    R4, gpu_timeout_polls
    LI    R5, 1000000
    STORE R5, R4, 0

    MOVI  R21, 0

frame:
    LI    R3, job_args
    LOAD  R4, R20, MMIO_VIDEO_FB_BACK_OFF   ; cambia en cada swap
    STORE R4, R3, 8                         ; p0 = framebuffer donde pintar
    STORE R21, R3, 12                       ; p1 = frame
    LI    R1, gpu_k_render
    MOVI  R2, NWARPS
    JAL   R31, gpu_run
    BNE   R1, R0, failed                    ; GPU_OK = 0

present:
    MOVI  R7, 1
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF      ; pedir el intercambio
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF      ; se aplica al empezar un frame
    BNE   R8, R0, wait_swap
    ADDI  R21, R21, 1
    BRA   frame

failed:
    HALT

; ---- GPU ----
; Argumentos (GETARG): +0 nwarps, +8 p0 = framebuffer, +12 p1 = frame.
;
;   R2 w (warp lógico)   R3 lane   R4 nwarps = el paso entre filas
;   R5 cy  R6 framebuffer  R7 t    R8 ya  R9 yb  R10 yc  (fases sin cx)
;   R11 cx  R12 puntero: palabra de ESTA lane en la línea 0 de la celda
;   R13..R15 las fases, luego R, G, B   R16 temporal   R17 el píxel / la palabra
;   R18 = lane >> 1 (celda dentro del grupo de 4)   R19 = lane * 4 (bytes)
;   R20 = 31  R21 = 5  R22 = 11  R23 = 6  R24 = 16  R25 = 60  R26 = 80
;   R27 = 1   R28 = 2560   R29 = 2
gpu_k_render:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R6, R1, 8                      ; framebuffer
    LOAD     R7, R1, 12                     ; t

    MOVI     R20, 31
    MOVI     R21, 5
    MOVI     R22, 11
    MOVI     R23, 6
    MOVI     R24, 16
    MOVI     R25, CELLS_Y
    MOVI     R26, CELLS_X
    MOVI     R27, 1
    MOVI     R28, 2560                      ; 4 líneas de 640 bytes
    MOVI     R29, 2

    SHR      R18, R3, R27                   ; lane >> 1
    SHL      R19, R3, R29                   ; lane * 4
    ADDI     R5, R2, 0                      ; cy = w

render_row:
    ; La misma `cy` en las 8 lanes: este salto es uniforme, no diverge.
    BGEU     R5, R25, render_end

    ; lo que no depende de cx
    ADD      R8, R5, R7                     ; ya = cy + t
    ADD      R16, R7, R7                    ; 2t
    SUB      R9, R16, R5                    ; yb = 2t - cy
    ADD      R10, R5, R5
    ADD      R10, R10, R16
    ADD      R10, R10, R7                   ; yc = 2cy + 3t
    MUL      R12, R5, R28
    ADD      R12, R12, R6
    ADD      R12, R12, R19                  ; fila + la palabra de esta lane
    ADDI     R11, R18, 0                    ; cx = lane >> 1

render_cell:
    ADD      R13, R11, R8                   ; pa = cx + ya
    ADD      R14, R11, R11
    ADD      R14, R14, R9                   ; pb = 2cx + yb
    SUB      R15, R10, R11                  ; pc = yc - cx
    ANDI     R13, R13, 63
    ANDI     R14, R14, 63
    ANDI     R15, R15, 63

    ; tri(p) para las tres fases, sin ramas
    ADDI     R13, R13, -32
    SAR      R16, R13, R20
    XOR      R13, R13, R16
    SUB      R13, R13, R16
    SHR      R16, R13, R21
    SUB      R13, R13, R16

    ADDI     R14, R14, -32
    SAR      R16, R14, R20
    XOR      R14, R14, R16
    SUB      R14, R14, R16
    SHR      R16, R14, R21
    SUB      R14, R14, R16

    ADDI     R15, R15, -32
    SAR      R16, R15, R20
    XOR      R15, R15, R16
    SUB      R15, R15, R16
    SHR      R16, R15, R21
    SUB      R15, R15, R16

    ; RGB565: R en 15:11, G en 10:5 (la onda por 2), B en 4:0
    SHL      R13, R13, R22
    SHL      R14, R14, R23                  ; (g << 1) << 5
    OR       R17, R13, R14
    OR       R17, R17, R15
    SHL      R16, R17, R24
    OR       R17, R17, R16                  ; el mismo píxel dos veces: una palabra

    ; 8 lanes = 8 palabras seguidas = 32 bytes: dos transacciones por STORE
    STORE    R17, R12, 0
    STORE    R17, R12, 640
    STORE    R17, R12, 1280
    STORE    R17, R12, 1920

    ADDI     R12, R12, 32                   ; 4 celdas más: 8 palabras
    ADDI     R11, R11, 4
    BLT      R11, R26, render_cell

    ADD      R5, R5, R4                     ; la fila de este warp que sigue
    BRA      render_row
render_end:
    EXIT

; ---- el runtime de CPU (detrás de su HALT: no hay linker) ----
.include "../dma/gpu_runtime.inc"

; ---- datos ----
job_args:
    .space 32
