; ============================================================
; life.inc - el juego de la vida, con la CPU, la GPU ingenua y la GPU bien puesta
;
; Rejilla de 160 x 104 celdas, cada una un cuadrado de 2 x 2 píxeles: ocupa las 208
; líneas de debajo de la gráfica de tiempos. La celda es una palabra (0 o 1) en una
; rejilla con borde de celdas muertas, y cada generación se calcula de la
; rejilla actual a la siguiente y se pinta en el framebuffer de atrás al mismo
; tiempo. Es un trabajo casi todo de memoria: ocho lecturas de vecinas, una de la
; propia celda y tres escrituras por celda, y casi nada de cálculo.
;
; La regla (B3/S23) sin comparar, con una máscara: con n vecinas vivas y la celda
; en s (0 o 1), el estado siguiente es el bit (2n + s) de 0xE0:
;
;     n = 3, s = 0  ->  bit 6        n = 3, s = 1  ->  bit 7
;     n = 2, s = 1  ->  bit 5        cualquier otro caso  ->  0
;
; ---- La rejilla ----
; Filas de 168 palabras (672 bytes, un múltiplo de 32) y 8 de relleno a la
; izquierda. Así la celda (x, y) está en la palabra (y + 1) * 168 + 8 + x, el
; relleno de la izquierda de una fila hace de borde derecho de la anterior, y el
; comienzo de cada fila queda alineado a 32 bytes: ocho celdas seguidas son una
; línea de la memoria entera.
;
; ---- Las tres maneras ----
;   demo_cpu       la CPU recorre las 16 640 celdas.
;   life_k_naive   un hilo por fila (104 filas entre 64 hilos). En cada instrucción
;                  las 8 lanes de un warp tocan 8 filas distintas, a 672 bytes una
;                  de otra: ninguna transacción se puede juntar.
;   life_k_good    un warp por fila, y las lanes son columnas seguidas. Cada
;                  instrucción toca 8 palabras consecutivas: 32 bytes.
; Los tres calculan exactamente lo mismo.
;
; Parámetros del trabajo (job_args): p0 rejilla actual, p1 rejilla siguiente,
; p2 framebuffer (ya en la línea 32), p3 el color de las celdas vivas.
; ============================================================

.equ LIFE_COLS,   160
.equ LIFE_ROWS,   104
.equ LIFE_STRIDE, 672               ; bytes por fila de la rejilla
.equ LIFE_GRID_A, 0x01060000
.equ LIFE_GRID_B, 0x01080000
.equ LIFE_BYTES,  71232             ; 106 filas de 672 bytes
.equ LIFE_FB_OFF, 20480             ; 32 líneas de 640 bytes

; ---- CPU: estado inicial ----
demo_setup:
    LI    R1, LIFE_GRID_A
    LI    R2, LIFE_GRID_B
    LI    R3, LIFE_BYTES
    ADD   R3, R1, R3                        ; fin de la primera rejilla
life_clear:
    STORE R0, R1, 0
    STORE R0, R2, 0
    ADDI  R1, R1, 4
    ADDI  R2, R2, 4
    BLT   R1, R3, life_clear
    RET

; ---- CPU: siembra una sopa al azar (25 % de celdas vivas) ----
life_reseed:
    LI    R1, life_cur
    LOAD  R2, R1, 0                         ; rejilla actual
    LI    R3, life_seed
    LOAD  R4, R3, 0
    LI    R5, 1664525
    LI    R6, 1013904223
    ADDI  R7, R2, 704                       ; celda (0, 0): una fila + 8 de relleno
    MOVI  R8, 0
    MOVI  R14, LIFE_COLS
    MOVI  R15, LIFE_ROWS
life_seed_row:
    MOVI  R9, 0
life_seed_cell:
    MUL   R4, R4, R5
    ADD   R4, R4, R6
    SHRI  R10, R4, 30
    SHRI  R11, R4, 29
    AND   R10, R10, R11
    ANDI  R10, R10, 1                       ; dos bits a uno de cada cuatro
    STORE R10, R7, 0
    ADDI  R7, R7, 4
    ADDI  R9, R9, 1
    BLT   R9, R14, life_seed_cell
    ADDI  R7, R7, 32                        ; salta el relleno hasta la fila siguiente
    ADDI  R8, R8, 1
    BLT   R8, R15, life_seed_row
    STORE R4, R3, 0
    RET

; ---- CPU: parámetros del trabajo, y siembra cuando toca ----
demo_prepare:
    ADDI  R29, R31, 0                       ; life_reseed pisa R31
    LI    R4, life_reseed_left
    LOAD  R5, R4, 0
    BNE   R5, R0, life_keep
    JAL   R31, life_reseed
    LI    R4, life_reseed_left
    LI    R5, life_reseed_period
    LOAD  R5, R5, 0
life_keep:
    ADDI  R5, R5, -1
    STORE R5, R4, 0

    LI    R3, job_args
    LI    R4, life_cur
    LOAD  R5, R4, 0
    STORE R5, R3, 8                         ; p0 = rejilla actual
    LI    R4, life_next
    LOAD  R5, R4, 0
    STORE R5, R3, 12                        ; p1 = rejilla siguiente
    LOAD  R5, R20, MMIO_VIDEO_FB_BACK_OFF
    ADDI  R5, R5, LIFE_FB_OFF
    STORE R5, R3, 16                        ; p2 = framebuffer, debajo de la gráfica
    SHLI  R6, R22, 2
    LI    R7, race_pixels
    ADD   R7, R7, R6
    LOAD  R5, R7, 0
    STORE R5, R3, 20                        ; p3 = color de las vivas en este método
    JR    R29

; ---- CPU: intercambia las rejillas ----
demo_advance:
    LI    R1, life_cur
    LI    R2, life_next
    LOAD  R3, R1, 0
    LOAD  R4, R2, 0
    STORE R4, R1, 0
    STORE R3, R2, 0
    RET

; ---- método 0: la CPU ----
demo_cpu:
    LI    R1, job_args
    LOAD  R2, R1, 8                         ; actual
    LOAD  R3, R1, 12                        ; siguiente
    LOAD  R4, R1, 16                        ; framebuffer
    LOAD  R5, R1, 20                        ; color
    MOVI  R6, 0xE0
    MOVI  R14, LIFE_COLS
    MOVI  R15, LIFE_ROWS
    ADDI  R8, R2, 704                       ; p: celda (0, 0) de la actual
    ADDI  R9, R3, 704                       ; q: la misma, en la siguiente
    ADDI  R10, R4, 0                        ; f: su píxel
    MOVI  R7, 0                             ; fila
life_cpu_row:
    MOVI  R11, 0                            ; columna
life_cpu_cell:
    LOAD  R12, R8, -676
    LOAD  R13, R8, -672
    ADD   R12, R12, R13
    LOAD  R13, R8, -668
    ADD   R12, R12, R13
    LOAD  R13, R8, -4
    ADD   R12, R12, R13
    LOAD  R13, R8, 4
    ADD   R12, R12, R13
    LOAD  R13, R8, 668
    ADD   R12, R12, R13
    LOAD  R13, R8, 672
    ADD   R12, R12, R13
    LOAD  R13, R8, 676
    ADD   R12, R12, R13                     ; n
    LOAD  R13, R8, 0                        ; s
    ADD   R12, R12, R12
    ADD   R12, R12, R13                     ; 2n + s
    SHR   R12, R6, R12
    ANDI  R12, R12, 1                       ; estado siguiente
    STORE R12, R9, 0
    SUB   R13, R0, R12
    AND   R13, R13, R5                      ; 0 o el color, en los dos píxeles
    STORE R13, R10, 0
    STORE R13, R10, 640
    ADDI  R8, R8, 4
    ADDI  R9, R9, 4
    ADDI  R10, R10, 4
    ADDI  R11, R11, 1
    BLT   R11, R14, life_cpu_cell
    ADDI  R8, R8, 32                        ; 672 - 640: la fila siguiente
    ADDI  R9, R9, 32
    ADDI  R10, R10, 640                     ; la segunda línea de píxeles ya estaba escrita
    ADDI  R7, R7, 1
    BLT   R7, R15, life_cpu_row
    RET

; ---- método 1: la GPU ingenua, un hilo por fila ----
;   R2 warp lógico  R3 lane  R4 nwarps  R5 actual  R6 siguiente  R7 framebuffer
;   R8 color  R9 = 0xE0  R10 filas  R11 columnas  R12 = 672  R13 = 1280
;   R14 y  R15 salto entre filas (los hilos)  R18 f  R19 p  R20 q  R21 x
;   R22 n  R23 s  R26 temporal
; El número de hilos es nwarps * nlanes = 64, y las filas 104: los hilos 0..39
; hacen dos y los 40..63 una. Es múltiplo de 8, así que ningún warp se divide.
life_k_naive:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R15, R1, 4                     ; nlanes
    LOAD     R5, R1, 8
    LOAD     R6, R1, 12
    LOAD     R7, R1, 16
    LOAD     R8, R1, 20
    MOVI     R9, 0xE0
    MOVI     R10, LIFE_ROWS
    MOVI     R11, LIFE_COLS
    MOVI     R12, LIFE_STRIDE
    MOVI     R13, 1280                      ; 2 líneas de 640 bytes
    MUL      R14, R2, R15
    ADD      R14, R14, R3                   ; y = hilo
    MUL      R15, R4, R15                   ; el paso: todos los hilos
naive_row:
    BGEU     R14, R10, life_end
    ADDI     R18, R14, 1
    MUL      R18, R18, R12
    ADDI     R18, R18, 32                   ; relleno de la izquierda
    ADD      R19, R5, R18
    ADD      R20, R6, R18
    MUL      R18, R14, R13
    ADD      R18, R18, R7
    MOVI     R21, 0
naive_cell:
    LOAD     R22, R19, -676
    LOAD     R26, R19, -672
    ADD      R22, R22, R26
    LOAD     R26, R19, -668
    ADD      R22, R22, R26
    LOAD     R26, R19, -4
    ADD      R22, R22, R26
    LOAD     R26, R19, 4
    ADD      R22, R22, R26
    LOAD     R26, R19, 668
    ADD      R22, R22, R26
    LOAD     R26, R19, 672
    ADD      R22, R22, R26
    LOAD     R26, R19, 676
    ADD      R22, R22, R26
    LOAD     R23, R19, 0
    ADD      R22, R22, R22
    ADD      R22, R22, R23
    SHR      R22, R9, R22
    ANDI     R22, R22, 1
    STORE    R22, R20, 0
    SUB      R26, R0, R22
    AND      R26, R26, R8
    STORE    R26, R18, 0
    STORE    R26, R18, 640
    ADDI     R19, R19, 4
    ADDI     R20, R20, 4
    ADDI     R18, R18, 4
    ADDI     R21, R21, 1
    BLT      R21, R11, naive_cell
    ADD      R14, R14, R15
    BRA      naive_row

; ---- método 2: la GPU bien puesta, un warp por fila ----
; Las mismas ocho lanes recorren la fila de ocho en ocho columnas: la lane l hace
; las columnas l, l + 8, l + 16... y R16 es su desplazamiento en bytes (4 * l).
; 104 filas entre 8 warps son 13 cada uno, y 160 columnas entre 8 lanes, 20.
life_k_good:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 8
    LOAD     R6, R1, 12
    LOAD     R7, R1, 16
    LOAD     R8, R1, 20
    MOVI     R9, 0xE0
    MOVI     R10, LIFE_ROWS
    MOVI     R11, LIFE_COLS
    MOVI     R12, LIFE_STRIDE
    MOVI     R13, 1280
    MOVI     R17, 2
    SHL      R16, R3, R17                   ; 4 * lane
    MOVI     R15, 8                         ; columnas por vuelta
    ADDI     R14, R2, 0                     ; y = warp lógico
good_row:
    BGEU     R14, R10, life_end
    ADDI     R18, R14, 1
    MUL      R18, R18, R12
    ADD      R18, R18, R16
    ADDI     R18, R18, 32                   ; relleno + la columna de esta lane
    ADD      R19, R5, R18
    ADD      R20, R6, R18
    MUL      R18, R14, R13
    ADD      R18, R18, R7
    ADD      R18, R18, R16
    ADDI     R21, R3, 0                     ; x = lane
good_cell:
    LOAD     R22, R19, -676
    LOAD     R26, R19, -672
    ADD      R22, R22, R26
    LOAD     R26, R19, -668
    ADD      R22, R22, R26
    LOAD     R26, R19, -4
    ADD      R22, R22, R26
    LOAD     R26, R19, 4
    ADD      R22, R22, R26
    LOAD     R26, R19, 668
    ADD      R22, R22, R26
    LOAD     R26, R19, 672
    ADD      R22, R22, R26
    LOAD     R26, R19, 676
    ADD      R22, R22, R26
    LOAD     R23, R19, 0
    ADD      R22, R22, R22
    ADD      R22, R22, R23
    SHR      R22, R9, R22
    ANDI     R22, R22, 1
    STORE    R22, R20, 0
    SUB      R26, R0, R22
    AND      R26, R26, R8
    STORE    R26, R18, 0
    STORE    R26, R18, 640
    ADDI     R19, R19, 32                   ; ocho columnas más
    ADDI     R20, R20, 32
    ADDI     R18, R18, 32
    ADD      R21, R21, R15
    BLT      R21, R11, good_cell
    ADD      R14, R14, R4
    BRA      good_row

life_end:
    EXIT

; ---- datos ----
race_kernels:
    .word 0, life_k_naive, life_k_good
race_pixels:
    .word 0x07E007E0, 0xFD20FD20, 0x07FF07FF    ; verde, naranja, cian
race_cycles:
    .word 0, 0, 0                               ; ciclos del último trabajo de cada método
race_period:
    .word 60
race_shift:
    .word 19                                    ; 524 288 ciclos (6,6 ms) por línea: 32 líneas = 210 ms
life_cur:
    .word LIFE_GRID_A
life_next:
    .word LIFE_GRID_B
life_seed:
    .word 12345
life_reseed_left:
    .word 0
life_reseed_period:
    .word 200
job_args:
    .space 32
