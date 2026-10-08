; ============================================================
; rotate.inc - una textura girando y acercándose, con la CPU, la GPU ingenua y la
;              GPU bien puesta
;
; Una textura de 128 x 128 texeles (un tablero de 16 x 16 con un degradado de
; color) que se repite sin fin, vista a través de una pantalla de 160 x 104
; celdas (2 x 2 píxeles) que la gira, la acerca y la desplaza. Cada celda de
; destino calcula qué texel le corresponde y lo copia: un gather.
;
; ---- Las coordenadas ----
; (u, v) en punto fijo Q7 (7 bits de fracción), en texeles. Pasar a la celda de la
; derecha suma (dux, dvx) y a la de abajo (-dvx, dux): es un giro con zoom.
; El texel de (u, v) está en la palabra
;
;     (v & 0x3F80) + ((u >> 7) & 127)       v & 0x3F80 ya es v_entero * 128
;
; de la textura, que envuelve sola. Con Q7 un solo desplazamiento por celda saca la
; columna, y la fila no necesita ninguno.
;
; ---- Qué se puede coalescer y qué no ----
; Cada celda hace UNA lectura (el texel, un gather) y DOS escrituras (las dos líneas
; de píxeles). Lo que sí se puede juntar es la escritura: con las lanes en celdas
; seguidas de una misma fila son 8 palabras contiguas (2 transacciones) y con un
; hilo por fila son 8 filas (8 transacciones). La lectura depende de a dónde
; mire cada lane: con la textura ampliada, celdas vecinas caen en el mismo texel
; o en texeles seguidos, y las lanes de una fila comparten líneas de memoria; las
; de filas distintas, no tanto. El ángulo se queda en +-45 grados para que eso siga siendo cierto.
;
; ---- Parámetros del trabajo (job_args) ----
; p0 framebuffer (línea 32), p1 u de la celda (0, 0), p2 v de la celda (0, 0),
; p3 dux, p4 dvx. La CPU los calcula cada fotograma con la tabla de senos.
; ============================================================

.equ ROT_COLS,  160
.equ ROT_ROWS,  104
.equ ROT_TEX,   0x010A0000          ; 128 x 128 palabras
.equ ROT_FB_OFF, 20480

; ---- CPU: pinta la textura una vez ----
; texel (tx, ty): tablero de 16 x 16; en las casillas claras un degradado
; rojo = tx >> 2, verde = ty >> 1, azul = 31 - rojo; las otras, gris oscuro.
demo_setup:
    LI    R12, ROT_TEX
    LI    R11, 65537
    MOVI  R4, 0                             ; ty
rot_tex_row:
    MOVI  R3, 0                             ; tx
rot_tex_texel:
    SHRI  R5, R3, 2
    SHLI  R6, R5, 11
    SHRI  R7, R4, 1
    SHLI  R7, R7, 5
    OR    R6, R6, R7
    MOVI  R8, 31
    SUB   R8, R8, R5
    OR    R6, R6, R8                        ; el color de la casilla clara
    SHRI  R9, R3, 4
    SHRI  R10, R4, 4
    XOR   R9, R9, R10
    ANDI  R9, R9, 1
    BNE   R9, R0, rot_tex_light
    MOVI  R6, 0x18C3
rot_tex_light:
    MUL   R6, R6, R11                       ; dos píxeles por palabra
    STORE R6, R12, 0
    ADDI  R12, R12, 4
    ADDI  R3, R3, 1
    MOVI  R13, 128
    BLT   R3, R13, rot_tex_texel
    ADDI  R4, R4, 1
    BLT   R4, R13, rot_tex_row
    RET

; ---- CPU: los parámetros del fotograma ----
;   a = |(f & 31) - 16| - 8                 el ángulo, en 64avos de vuelta (-8..8)
;   s = 48 + |((3 f) & 63) - 32|            el paso por celda, en Q7 (48..80)
;   dux = cos(a) s >> 7     dvx = sin(a) s >> 7
;   centro de la pantalla -> (8192 + 40 f, 8192 + 24 f), el centro de la textura
;   (u, v) de la celda (0, 0) = centro - 80 (dux, dvx) - 52 (-dvx, dux)
demo_prepare:
    ANDI  R4, R21, 31
    ADDI  R4, R4, -16
    BGE   R4, R0, rot_a_pos
    SUB   R4, R0, R4
rot_a_pos:
    ADDI  R4, R4, -8                        ; a
    ANDI  R5, R4, 63
    SHLI  R5, R5, 2
    LI    R6, rot_sin
    ADD   R6, R6, R5
    LOAD  R7, R6, 0                         ; sin a
    ADDI  R5, R4, 16
    ANDI  R5, R5, 63
    SHLI  R5, R5, 2
    LI    R6, rot_sin
    ADD   R6, R6, R5
    LOAD  R8, R6, 0                         ; cos a
    MOVI  R9, 3
    MUL   R9, R21, R9
    ANDI  R9, R9, 63
    ADDI  R9, R9, -32
    BGE   R9, R0, rot_s_pos
    SUB   R9, R0, R9
rot_s_pos:
    ADDI  R9, R9, 48                        ; s
    MUL   R10, R8, R9
    SARI  R10, R10, 7                       ; dux
    MUL   R11, R7, R9
    SARI  R11, R11, 7                       ; dvx
    MOVI  R12, 40
    MUL   R12, R21, R12
    ADDI  R12, R12, 8192                    ; u del centro
    MOVI  R13, 24
    MUL   R13, R21, R13
    ADDI  R13, R13, 8192                    ; v del centro
    MOVI  R14, 80
    MUL   R15, R14, R10                     ; 80 dux
    SUB   R12, R12, R15
    MUL   R15, R14, R11                     ; 80 dvx
    SUB   R13, R13, R15
    MOVI  R14, 52
    MUL   R15, R14, R11                     ; 52 dvx
    ADD   R12, R12, R15                     ; u00
    MUL   R15, R14, R10                     ; 52 dux
    SUB   R13, R13, R15                     ; v00
    LI    R3, job_args
    LOAD  R5, R20, MMIO_VIDEO_FB_BACK_OFF
    ADDI  R5, R5, ROT_FB_OFF
    STORE R5, R3, 8                         ; p0 = framebuffer
    STORE R12, R3, 12                       ; p1 = u00
    STORE R13, R3, 16                       ; p2 = v00
    STORE R10, R3, 20                       ; p3 = dux
    STORE R11, R3, 24                       ; p4 = dvx
    RET

demo_advance:
    RET

; ---- método 0: la CPU ----
demo_cpu:
    LI    R1, job_args
    LOAD  R2, R1, 8                         ; f
    LOAD  R3, R1, 12                        ; u00
    LOAD  R4, R1, 16                        ; v00
    LOAD  R5, R1, 20                        ; dux
    LOAD  R6, R1, 24                        ; dvx
    LI    R7, ROT_TEX
    MOVI  R14, ROT_COLS
    MOVI  R15, ROT_ROWS
    MOVI  R8, 0                             ; y
rot_cpu_row:
    MUL   R9, R8, R6
    SUB   R10, R3, R9                       ; u = u00 - y dvx
    MUL   R9, R8, R5
    ADD   R11, R4, R9                       ; v = v00 + y dux
    MOVI  R12, 0                            ; x
rot_cpu_cell:
    SHRI  R9, R10, 7
    ANDI  R9, R9, 127
    ANDI  R13, R11, 0x3F80
    ADD   R9, R9, R13
    SHLI  R9, R9, 2
    ADD   R9, R9, R7
    LOAD  R9, R9, 0                         ; el texel
    STORE R9, R2, 0
    STORE R9, R2, 640
    ADD   R10, R10, R5
    ADD   R11, R11, R6
    ADDI  R2, R2, 4
    ADDI  R12, R12, 1
    BLT   R12, R14, rot_cpu_cell
    ADDI  R2, R2, 640                       ; las dos líneas de esta fila ya están
    ADDI  R8, R8, 1
    BLT   R8, R15, rot_cpu_row
    RET

; ---- método 1: la GPU ingenua, un hilo por fila ----
;   R2 warp lógico  R3 lane  R4 nwarps  R5 fb  R6 u00  R7 v00  R8 dux  R9 dvx
;   R10 filas  R11 columnas  R12 = 7  R13 = 2  R14 y  R15 salto entre filas
;   R17 textura  R18 f  R19 u  R20 v  R21 x  R22 índice  R23 temporal  R24 texel
;   R27 = 1280  R28 temporal
rot_k_naive:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R15, R1, 4                     ; nlanes
    LOAD     R5, R1, 8
    LOAD     R6, R1, 12
    LOAD     R7, R1, 16
    LOAD     R8, R1, 20
    LOAD     R9, R1, 24
    MOVI     R10, ROT_ROWS
    MOVI     R11, ROT_COLS
    MOVI     R12, 7
    MOVI     R13, 2
    LI       R17, ROT_TEX
    MOVI     R27, 1280
    MUL      R14, R2, R15
    ADD      R14, R14, R3                   ; y = hilo
    MUL      R15, R4, R15                   ; el paso: todos los hilos
rot_n_row:
    BGEU     R14, R10, rot_end
    MUL      R28, R14, R9
    SUB      R19, R6, R28                   ; u = u00 - y dvx
    MUL      R28, R14, R8
    ADD      R20, R7, R28                   ; v = v00 + y dux
    MUL      R18, R14, R27
    ADD      R18, R18, R5                   ; f
    MOVI     R21, 0
rot_n_cell:
    SHR      R22, R19, R12
    ANDI     R22, R22, 127
    ANDI     R23, R20, 0x3F80
    ADD      R22, R22, R23
    SHL      R22, R22, R13
    ADD      R22, R22, R17
    LOAD     R24, R22, 0
    STORE    R24, R18, 0
    STORE    R24, R18, 640
    ADD      R19, R19, R8
    ADD      R20, R20, R9
    ADDI     R18, R18, 4
    ADDI     R21, R21, 1
    BLT      R21, R11, rot_n_cell
    ADD      R14, R14, R15
    BRA      rot_n_row

; ---- método 2: la GPU bien puesta, un warp por fila ----
; La lane l hace las columnas l, l + 8, l + 16...: R16 = 4 * l bytes, R25 = 8 dux,
; R26 = 8 dvx (lo que avanzan u y v en una vuelta), R15 = 8.
rot_k_good:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 8
    LOAD     R6, R1, 12
    LOAD     R7, R1, 16
    LOAD     R8, R1, 20
    LOAD     R9, R1, 24
    MOVI     R10, ROT_ROWS
    MOVI     R11, ROT_COLS
    MOVI     R12, 7
    MOVI     R13, 2
    LI       R17, ROT_TEX
    MOVI     R27, 1280
    MOVI     R15, 8
    SHL      R16, R3, R13                   ; 4 * lane
    MUL      R25, R8, R15
    MUL      R26, R9, R15
    ADDI     R14, R2, 0                     ; y = warp lógico
rot_g_row:
    BGEU     R14, R10, rot_end
    MUL      R28, R14, R9
    SUB      R19, R6, R28
    MUL      R28, R3, R8
    ADD      R19, R19, R28                  ; u = u00 - y dvx + lane dux
    MUL      R28, R14, R8
    ADD      R20, R7, R28
    MUL      R28, R3, R9
    ADD      R20, R20, R28                  ; v = v00 + y dux + lane dvx
    MUL      R18, R14, R27
    ADD      R18, R18, R5
    ADD      R18, R18, R16                  ; f + la columna de esta lane
    ADDI     R21, R3, 0                     ; x = lane
rot_g_cell:
    SHR      R22, R19, R12
    ANDI     R22, R22, 127
    ANDI     R23, R20, 0x3F80
    ADD      R22, R22, R23
    SHL      R22, R22, R13
    ADD      R22, R22, R17
    LOAD     R24, R22, 0
    STORE    R24, R18, 0
    STORE    R24, R18, 640
    ADD      R19, R19, R25
    ADD      R20, R20, R26
    ADDI     R18, R18, 32
    ADD      R21, R21, R15
    BLT      R21, R11, rot_g_cell
    ADD      R14, R14, R4
    BRA      rot_g_row

rot_end:
    EXIT

; ---- datos ----
race_kernels:
    .word 0, rot_k_naive, rot_k_good
race_pixels:
    .word 0x07E007E0, 0xFD20FD20, 0x07FF07FF    ; colores de la gráfica: verde, naranja, cian
race_cycles:
    .word 0, 0, 0                               ; ciclos del último trabajo de cada método
race_period:
    .word 60
race_shift:
    .word 17                                    ; 131 072 ciclos (1,6 ms) por línea
rot_sin:                                        ; 128 * sin(2 pi k / 64), k = 0..63
    .word 0, 13, 25, 37, 49, 60, 71, 81
    .word 91, 99, 106, 113, 118, 122, 126, 127
    .word 128, 127, 126, 122, 118, 113, 106, 99
    .word 91, 81, 71, 60, 49, 37, 25, 13
    .word 0, -13, -25, -37, -49, -60, -71, -81
    .word -91, -99, -106, -113, -118, -122, -126, -127
    .word -128, -127, -126, -122, -118, -113, -106, -99
    .word -91, -81, -71, -60, -49, -37, -25, -13
job_args:
    .space 32
