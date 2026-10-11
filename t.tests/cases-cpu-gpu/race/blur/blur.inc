; ============================================================
; blur.inc - difusión de calor: un desenfoque 3 x 3 repetido, con la CPU, la GPU
;            ingenua y la GPU bien puesta
;
; La misma rejilla que life.inc (160 x 104 celdas de 2 x 2 píxeles, filas de 168
; palabras con borde muerto), pero cada celda guarda una intensidad de 0 a 255 y
; en cada fotograma:
;
;   1. la CPU enciende tres puntos calientes que se mueven (un bloque de 3 x 3 a
;      255, con ondas triangulares de periodo distinto en x y en y);
;   2. cada celda pasa a ser un promedio de su vecindad 3 x 3 con pesos
;      1 2 1 / 2 4 2 / 1 2 1 (suman 16), con una pérdida del 6 % por fotograma:
;
;          siguiente = (4c + 2 (N + S + E + W) + (NO + NE + SO + SE)) * 15 >> 8
;
;   3. la celda se pinta con una paleta que va del negro al amarillo:
;      rojo = (v << 8) & 0xF800, verde = (v << 3) & 0x07E0.
;
; Los puntos dejan una estela que se apaga. Es otra vez un trabajo de memoria
; (nueve lecturas y tres escrituras por celda) con algo más de cálculo que la
; vida: un producto y tres desplazamientos.
;
; Los tres métodos son los de life.inc (demo_cpu, blur_k_naive, blur_k_good) y se
; reparten el trabajo igual: un hilo por fila contra un warp por fila con las
; lanes en columnas seguidas.
;
; Parámetros del trabajo (job_args): p0 rejilla actual, p1 rejilla siguiente,
; p2 framebuffer (ya en la línea 32). No usa color: la paleta es el calor.
; ============================================================

.equ BLUR_COLS,   160
.equ BLUR_ROWS,   104
.equ BLUR_STRIDE, 672
.equ BLUR_GRID_A, 0x01060000
.equ BLUR_GRID_B, 0x01080000
.equ BLUR_BYTES,  71232
.equ BLUR_FB_OFF, 20480

; ---- CPU: estado inicial: las dos rejillas a cero ----
demo_setup:
    LI    R1, BLUR_GRID_A
    LI    R2, BLUR_GRID_B
    LI    R3, BLUR_BYTES
    ADD   R3, R1, R3
blur_clear:
    STORE R0, R1, 0
    STORE R0, R2, 0
    ADDI  R1, R1, 4
    ADDI  R2, R2, 4
    BLT   R1, R3, blur_clear
    RET

; ---- CPU: enciende los puntos calientes y deja los parámetros del trabajo ----
; Cada punto tiene un periodo en x y otro en y (blur_spots: sx, sy); su posición
; es una onda triangular de la fase (fotograma * periodo): x en 16..144, y en 16..80.
demo_prepare:
    LI    R4, blur_cur
    LOAD  R4, R4, 0                         ; rejilla actual
    MOVI  R5, 0                             ; punto
blur_spot:
    SHLI  R6, R5, 3
    LI    R7, blur_spots
    ADD   R7, R7, R6
    LOAD  R8, R7, 0                         ; sx
    LOAD  R9, R7, 4                         ; sy
    MUL   R10, R21, R8
    ANDI  R10, R10, 255
    ADDI  R10, R10, -128
    BGE   R10, R0, blur_x_pos
    SUB   R10, R0, R10
blur_x_pos:
    ADDI  R10, R10, 16                      ; x
    MUL   R11, R21, R9
    ADDI  R11, R11, 64
    ANDI  R11, R11, 127
    ADDI  R11, R11, -64
    BGE   R11, R0, blur_y_pos
    SUB   R11, R0, R11
blur_y_pos:
    ADDI  R11, R11, 16                      ; y
    ADDI  R12, R11, 1
    LI    R13, BLUR_STRIDE
    MUL   R12, R12, R13
    SHLI  R13, R10, 2
    ADD   R12, R12, R13
    ADD   R12, R12, R4
    ADDI  R12, R12, 32                      ; la celda del punto
    MOVI  R13, 255
    STORE R13, R12, -676
    STORE R13, R12, -672
    STORE R13, R12, -668
    STORE R13, R12, -4
    STORE R13, R12, 0
    STORE R13, R12, 4
    STORE R13, R12, 668
    STORE R13, R12, 672
    STORE R13, R12, 676
    ADDI  R5, R5, 1
    MOVI  R6, 3
    BLT   R5, R6, blur_spot

    LI    R3, job_args
    STORE R4, R3, 8                         ; p0 = rejilla actual
    LI    R4, blur_next
    LOAD  R5, R4, 0
    STORE R5, R3, 12                        ; p1 = rejilla siguiente
    LOAD  R5, R20, MMIO_VIDEO_FB_BACK_OFF
    ADDI  R5, R5, BLUR_FB_OFF
    STORE R5, R3, 16                        ; p2 = framebuffer, debajo de la gráfica
    RET

; ---- CPU: intercambia las rejillas ----
demo_advance:
    LI    R1, blur_cur
    LI    R2, blur_next
    LOAD  R3, R1, 0
    LOAD  R4, R2, 0
    STORE R4, R1, 0
    STORE R3, R2, 0
    RET

; ---- método 0: la CPU ----
demo_cpu:
    LI    R1, job_args
    LOAD  R8, R1, 8
    ADDI  R8, R8, 704                       ; p: celda (0, 0) de la actual
    LOAD  R9, R1, 12
    ADDI  R9, R9, 704                       ; q: la misma, en la siguiente
    LOAD  R10, R1, 16                       ; f: su píxel
    MOVI  R2, 15
    LI    R3, 0xF800
    MOVI  R4, 0x07E0
    LI    R5, 65537
    MOVI  R14, BLUR_COLS
    MOVI  R15, BLUR_ROWS
    MOVI  R7, 0                             ; fila
blur_cpu_row:
    MOVI  R11, 0                            ; columna
blur_cpu_cell:
    LOAD  R12, R8, -676
    LOAD  R13, R8, -668
    ADD   R12, R12, R13
    LOAD  R13, R8, 668
    ADD   R12, R12, R13
    LOAD  R13, R8, 676
    ADD   R12, R12, R13                     ; esquinas
    LOAD  R1, R8, -672
    LOAD  R13, R8, -4
    ADD   R1, R1, R13
    LOAD  R13, R8, 4
    ADD   R1, R1, R13
    LOAD  R13, R8, 672
    ADD   R1, R1, R13                       ; lados
    LOAD  R13, R8, 0
    ADD   R1, R1, R13
    ADD   R1, R1, R13                       ; lados + 2 centro
    ADD   R1, R1, R1
    ADD   R12, R12, R1                      ; la suma de pesos (16 en total)
    MUL   R12, R12, R2
    SHRI  R12, R12, 8
    STORE R12, R9, 0
    SHLI  R13, R12, 8
    AND   R13, R13, R3
    SHLI  R1, R12, 3
    AND   R1, R1, R4
    OR    R13, R13, R1
    MUL   R13, R13, R5                      ; el mismo píxel dos veces
    STORE R13, R10, 0
    STORE R13, R10, 640
    ADDI  R8, R8, 4
    ADDI  R9, R9, 4
    ADDI  R10, R10, 4
    ADDI  R11, R11, 1
    BLT   R11, R14, blur_cpu_cell
    ADDI  R8, R8, 32
    ADDI  R9, R9, 32
    ADDI  R10, R10, 640
    ADDI  R7, R7, 1
    BLT   R7, R15, blur_cpu_row
    RET

; ---- método 1: la GPU ingenua, un hilo por fila ----
;   R2 warp lógico  R3 lane  R4 nwarps  R5 actual  R6 siguiente  R7 framebuffer
;   R8 = 15  R9 = 8  R10 filas  R11 columnas  R12 = 672  R13 = 1280
;   R14 y  R15 salto entre filas  R17 = 3  R18 f  R19 p  R20 q  R21 x
;   R22 esquinas, luego la suma  R23 lados  R24, R28, R29 temporales
;   R25 = 0xF800  R26 = 0x07E0  R27 = 65537
blur_k_naive:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R15, R1, 4                     ; nlanes
    LOAD     R5, R1, 8
    LOAD     R6, R1, 12
    LOAD     R7, R1, 16
    MOVI     R8, 15
    MOVI     R9, 8
    MOVI     R10, BLUR_ROWS
    MOVI     R11, BLUR_COLS
    MOVI     R12, BLUR_STRIDE
    MOVI     R13, 1280
    MOVI     R17, 3
    LI       R25, 0xF800
    MOVI     R26, 0x07E0
    LI       R27, 65537
    MUL      R14, R2, R15
    ADD      R14, R14, R3                   ; y = hilo
    MUL      R15, R4, R15                   ; el paso: todos los hilos
blur_n_row:
    BGEU     R14, R10, blur_end
    ADDI     R18, R14, 1
    MUL      R18, R18, R12
    ADDI     R18, R18, 32
    ADD      R19, R5, R18
    ADD      R20, R6, R18
    MUL      R18, R14, R13
    ADD      R18, R18, R7
    MOVI     R21, 0
blur_n_cell:
    LOAD     R22, R19, -676
    LOAD     R24, R19, -668
    ADD      R22, R22, R24
    LOAD     R24, R19, 668
    ADD      R22, R22, R24
    LOAD     R24, R19, 676
    ADD      R22, R22, R24
    LOAD     R23, R19, -672
    LOAD     R24, R19, -4
    ADD      R23, R23, R24
    LOAD     R24, R19, 4
    ADD      R23, R23, R24
    LOAD     R24, R19, 672
    ADD      R23, R23, R24
    LOAD     R24, R19, 0
    ADD      R23, R23, R24
    ADD      R23, R23, R24
    ADD      R23, R23, R23
    ADD      R22, R22, R23
    MUL      R22, R22, R8
    SHR      R22, R22, R9
    STORE    R22, R20, 0
    SHL      R28, R22, R9
    AND      R28, R28, R25
    SHL      R29, R22, R17
    AND      R29, R29, R26
    OR       R28, R28, R29
    MUL      R28, R28, R27
    STORE    R28, R18, 0
    STORE    R28, R18, 640
    ADDI     R19, R19, 4
    ADDI     R20, R20, 4
    ADDI     R18, R18, 4
    ADDI     R21, R21, 1
    BLT      R21, R11, blur_n_cell
    ADD      R14, R14, R15
    BRA      blur_n_row

; ---- método 2: la GPU bien puesta, un warp por fila ----
; R16 = 4 * lane; R15 = 8 columnas por vuelta; el resto como en la ingenua.
blur_k_good:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 8
    LOAD     R6, R1, 12
    LOAD     R7, R1, 16
    MOVI     R8, 15
    MOVI     R9, 8
    MOVI     R10, BLUR_ROWS
    MOVI     R11, BLUR_COLS
    MOVI     R12, BLUR_STRIDE
    MOVI     R13, 1280
    LI       R25, 0xF800
    MOVI     R26, 0x07E0
    LI       R27, 65537
    MOVI     R17, 2
    SHL      R16, R3, R17                   ; 4 * lane
    MOVI     R17, 3
    MOVI     R15, 8                         ; columnas por vuelta
    ADDI     R14, R2, 0                     ; y = warp lógico
blur_g_row:
    BGEU     R14, R10, blur_end
    ADDI     R18, R14, 1
    MUL      R18, R18, R12
    ADD      R18, R18, R16
    ADDI     R18, R18, 32
    ADD      R19, R5, R18
    ADD      R20, R6, R18
    MUL      R18, R14, R13
    ADD      R18, R18, R7
    ADD      R18, R18, R16
    ADDI     R21, R3, 0                     ; x = lane
blur_g_cell:
    LOAD     R22, R19, -676
    LOAD     R24, R19, -668
    ADD      R22, R22, R24
    LOAD     R24, R19, 668
    ADD      R22, R22, R24
    LOAD     R24, R19, 676
    ADD      R22, R22, R24
    LOAD     R23, R19, -672
    LOAD     R24, R19, -4
    ADD      R23, R23, R24
    LOAD     R24, R19, 4
    ADD      R23, R23, R24
    LOAD     R24, R19, 672
    ADD      R23, R23, R24
    LOAD     R24, R19, 0
    ADD      R23, R23, R24
    ADD      R23, R23, R24
    ADD      R23, R23, R23
    ADD      R22, R22, R23
    MUL      R22, R22, R8
    SHR      R22, R22, R9
    STORE    R22, R20, 0
    SHL      R28, R22, R9
    AND      R28, R28, R25
    SHL      R29, R22, R17
    AND      R29, R29, R26
    OR       R28, R28, R29
    MUL      R28, R28, R27
    STORE    R28, R18, 0
    STORE    R28, R18, 640
    ADDI     R19, R19, 32
    ADDI     R20, R20, 32
    ADDI     R18, R18, 32
    ADD      R21, R21, R15
    BLT      R21, R11, blur_g_cell
    ADD      R14, R14, R4
    BRA      blur_g_row

blur_end:
    EXIT

; ---- datos ----
race_kernels:
    .word 0, blur_k_naive, blur_k_good
race_pixels:
    .word 0x07E007E0, 0xFD20FD20, 0x07FF07FF    ; colores de la gráfica: verde, naranja, cian
race_cycles:
    .word 0, 0, 0                               ; ciclos del último trabajo de cada método
race_period:
    .word 60
race_shift:
    .word 19                                    ; 524 288 ciclos (6,6 ms) por línea
blur_cur:
    .word BLUR_GRID_A
blur_next:
    .word BLUR_GRID_B
blur_spots:
    .word 3, 2, 2, 5, 5, 3                      ; (sx, sy) de cada punto caliente
job_args:
    .space 32
