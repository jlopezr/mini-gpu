; ============================================================
; cube.inc - un cubo sólido con texturas girando sobre dos ejes, con la CPU, la
;            GPU ingenua y la GPU bien puesta
;
; Proyección ortográfica de un cubo de medio lado L = 32 celdas, centrado en la
; celda (80, 52) de una pantalla de 160 x 104 celdas (2 x 2 píxeles). Gira sobre Y
; (b = fotograma, en 64avos de vuelta) y se inclina sobre X (a = 3/4 del
; fotograma). Sin perspectiva no hay divisiones por píxel, y un cubo convexo
; enseña, de las seis caras, solo tres que no se tapan: ni z-buffer ni triángulos.
;
; ---- Qué hace la CPU en cada fotograma (demo_prepare) ----
; La matriz R = Rx(a) Ry(b) en Q7 y, de cada eje i, la cara que mira a la
; cámara (la de signo s = signo de R[2][i]; si es 0 está de canto y no se ve). Para
; esa cara, la función que lleva una celda (x, y) a coordenadas (u, v) de su
; textura es afín, y la CPU calcula sus seis coeficientes con una división por cara
; y eje:
;
;     q   = (R[2][m] << 14) / R[2][i]                     m = los otros dos ejes
;     ux  = ((R[0][m] << 7) - (q R[0][i] >> 7)) >> 7      uy igual con la fila 1
;     u00 = 4096 + (s q >> 2) - 80 ux - 52 uy             (u, v en Q7, de 0 a 8192)
;
; ---- Qué hace cada celda ----
; Prueba las tres caras en orden. En cada una, (u, v) cae dentro si los dos son
; menores que LIM sin signo, y es un solo salto por coordenada. Si cae, lee el
; texel (un gather) y escribe el píxel; si no cae en ninguna, es fondo. Cada cara se
; da por buena 2 texeles de más por cada lado (EPS): así donde dos caras se tocan no
; queda ninguna rendija, y el que sobra lo tapa el borde negro de la textura (que se
; repite por los dos lados con el AND). Las 6 texturas son de 64 x 64 y llevan ese
; borde de 2 texeles.
;
; ---- Los tres métodos ----
; Como en rotate.inc, pero las lanes de un mismo warp pueden tomar caminos
; distintos en cada celda: es lo que cuesta la divergencia. Con las lanes en una
; fila (bien puesta) casi siempre caen en la misma cara; con un hilo por fila
; (ingenua), cada lane está en una fila distinta y se separan más a menudo.
;
; Tabla de caras (cube_faces, 3 entradas de 32 bytes, una por eje):
;   +0 base de la textura  +4 u00  +8 v00  +12 ux  +16 vx  +20 uy  +24 vy
; (u00 y v00 ya llevan sumado EPS: así la prueba es directa).
; ============================================================

.equ CUBE_COLS, 160
.equ CUBE_ROWS, 104
.equ CUBE_TEX,  0x010A0000          ; 6 texturas de 64 x 64 palabras (16 KiB cada una)
.equ CUBE_FB_OFF, 20480
.equ CUBE_LIM,  8704                ; 8192 + 2 * 256
.equ CUBE_BG,   0x10A210A2          ; el fondo: verde azulado oscuro, dos píxeles

; ---- CPU: las seis texturas, una vez ----
; Eje 0: tablero; eje 1: rayas en diagonal; eje 2: puntos (el AND de dos bits).
; Cada textura usa dos colores (cube_pal) y un borde negro de 2 texeles.
demo_setup:
    LI    R12, CUBE_TEX
    LI    R11, 65537
    MOVI  R1, 0                             ; textura
cube_tex_id:
    LI    R3, cube_pal
    SHLI  R4, R1, 3
    ADD   R3, R3, R4
    LOAD  R5, R3, 0                         ; color 0
    LOAD  R6, R3, 4                         ; color 1
    SHRI  R2, R1, 1                         ; patrón = eje
    MOVI  R4, 0                             ; ty
cube_tex_row:
    MOVI  R3, 0                             ; tx
cube_tex_texel:
    BNE   R2, R0, cube_p1
    SHRI  R7, R3, 3
    SHRI  R8, R4, 3
    XOR   R7, R7, R8
    ANDI  R7, R7, 1
    BRA   cube_pdone
cube_p1:
    MOVI  R8, 1
    BNE   R2, R8, cube_p2
    ADD   R7, R3, R4
    SHRI  R7, R7, 3
    ANDI  R7, R7, 1
    BRA   cube_pdone
cube_p2:
    SHRI  R7, R3, 2
    SHRI  R8, R4, 2
    AND   R7, R7, R8
    ANDI  R7, R7, 1
cube_pdone:
    ADDI  R9, R5, 0
    BEQ   R7, R0, cube_c0
    ADDI  R9, R6, 0
cube_c0:
    ADDI  R7, R3, -2
    MOVI  R8, 60
    BGEU  R7, R8, cube_ring
    ADDI  R7, R4, -2
    BGEU  R7, R8, cube_ring
    BRA   cube_store
cube_ring:
    MOVI  R9, 0                             ; el borde
cube_store:
    MUL   R9, R9, R11                       ; dos píxeles por palabra
    STORE R9, R12, 0
    ADDI  R12, R12, 4
    ADDI  R3, R3, 1
    MOVI  R8, 64
    BLT   R3, R8, cube_tex_texel
    ADDI  R4, R4, 1
    BLT   R4, R8, cube_tex_row
    ADDI  R1, R1, 1
    MOVI  R8, 6
    BLT   R1, R8, cube_tex_id
    RET

; ---- CPU: la matriz, las tres caras y los parámetros del trabajo ----
demo_prepare:
    ANDI  R4, R21, 63                       ; b
    MOVI  R5, 3
    MUL   R5, R21, R5
    SHRI  R5, R5, 2
    ANDI  R5, R5, 63                        ; a
    LI    R6, cube_sin
    SHLI  R7, R4, 2
    ADD   R7, R7, R6
    LOAD  R8, R7, 0                         ; sb
    ADDI  R7, R4, 16
    ANDI  R7, R7, 63
    SHLI  R7, R7, 2
    ADD   R7, R7, R6
    LOAD  R9, R7, 0                         ; cb
    SHLI  R7, R5, 2
    ADD   R7, R7, R6
    LOAD  R10, R7, 0                        ; sa
    ADDI  R7, R5, 16
    ANDI  R7, R7, 63
    SHLI  R7, R7, 2
    ADD   R7, R7, R6
    LOAD  R11, R7, 0                        ; ca
    LI    R12, cube_m
    STORE R9, R12, 0                        ; fila 0: cb, 0, sb
    STORE R0, R12, 4
    STORE R8, R12, 8
    MUL   R13, R10, R8                      ; fila 1: sa sb, ca, -sa cb
    SARI  R13, R13, 7
    STORE R13, R12, 12
    STORE R11, R12, 16
    MUL   R13, R10, R9
    SUB   R13, R0, R13
    SARI  R13, R13, 7
    STORE R13, R12, 20
    MUL   R13, R11, R8                      ; fila 2: -ca sb, sa, ca cb
    SUB   R13, R0, R13
    SARI  R13, R13, 7
    STORE R13, R12, 24
    STORE R10, R12, 28
    MUL   R13, R11, R9
    SARI  R13, R13, 7
    STORE R13, R12, 32

    MOVI  R5, 0                             ; eje i
cube_face:
    LI    R12, cube_m
    ADDI  R6, R5, 6
    SHLI  R6, R6, 2
    ADD   R6, R12, R6
    LOAD  R7, R6, 0                         ; R[2][i]
    SHLI  R13, R5, 5
    LI    R14, cube_faces
    ADD   R13, R13, R14                     ; la entrada de esta cara
    BNE   R7, R0, cube_valid
    LI    R6, 0x40000000                    ; de canto: u y v fuera de rango siempre
    STORE R0, R13, 0
    STORE R6, R13, 4
    STORE R6, R13, 8
    STORE R0, R13, 12
    STORE R0, R13, 16
    STORE R0, R13, 20
    STORE R0, R13, 24
    BRA   cube_next
cube_valid:
    MOVI  R8, 1                             ; s
    BGE   R7, R0, cube_spos
    MOVI  R8, -1
cube_spos:
    ADDI  R9, R5, 1                         ; j
    MOVI  R6, 3
    BLT   R9, R6, cube_jok
    MOVI  R9, 0
cube_jok:
    ADDI  R10, R5, 2                        ; k
    BLT   R10, R6, cube_kok
    ADDI  R10, R10, -3
cube_kok:
    SHLI  R11, R5, 1                        ; textura = 2 i + (s < 0)
    BGE   R8, R0, cube_idok
    ADDI  R11, R11, 1
cube_idok:
    SHLI  R11, R11, 14
    LI    R6, CUBE_TEX
    ADD   R11, R11, R6
    STORE R11, R13, 0
    SHLI  R2, R5, 2
    ADD   R2, R12, R2
    LOAD  R15, R2, 0                        ; R[0][i]
    LOAD  R16, R2, 12                       ; R[1][i]
    MOVI  R14, 0                            ; 0: u (eje j), 1: v (eje k)
cube_axis:
    ADDI  R6, R9, 0
    BEQ   R14, R0, cube_axm
    ADDI  R6, R10, 0
cube_axm:
    ADDI  R1, R6, 6
    SHLI  R1, R1, 2
    ADD   R1, R12, R1
    LOAD  R1, R1, 0                         ; R[2][m]
    SHLI  R1, R1, 14
    DIV   R1, R1, R7                        ; q
    SHLI  R2, R6, 2
    ADD   R2, R12, R2
    LOAD  R3, R2, 0                         ; R[0][m]
    LOAD  R4, R2, 12                        ; R[1][m]
    SHLI  R2, R3, 7
    MUL   R3, R1, R15
    SARI  R3, R3, 7
    SUB   R2, R2, R3                        ; cx
    SHLI  R3, R4, 7
    MUL   R4, R1, R16
    SARI  R4, R4, 7
    SUB   R3, R3, R4                        ; cy
    MUL   R4, R8, R1                        ; s q
    SARI  R2, R2, 7                         ; paso en x
    SARI  R3, R3, 7                         ; paso en y
    SARI  R4, R4, 2
    ADDI  R4, R4, 4352                      ; 4096 + EPS
    MOVI  R18, 80
    MUL   R18, R18, R2
    SUB   R4, R4, R18
    MOVI  R18, 52
    MUL   R18, R18, R3
    SUB   R4, R4, R18                       ; u00 (o v00)
    SHLI  R18, R14, 2
    ADD   R18, R13, R18
    STORE R4, R18, 4
    STORE R2, R18, 12
    STORE R3, R18, 20
    ADDI  R14, R14, 1
    MOVI  R18, 2
    BLT   R14, R18, cube_axis
cube_next:
    ADDI  R5, R5, 1
    MOVI  R18, 3
    BLT   R5, R18, cube_face

    LI    R3, job_args
    LOAD  R5, R20, MMIO_VIDEO_FB_BACK_OFF
    ADDI  R5, R5, CUBE_FB_OFF
    STORE R5, R3, 8                         ; p0 = framebuffer, debajo de la gráfica
    RET

demo_advance:
    RET

; ---- método 0: la CPU ----
;   R1..R6 u0 v0 u1 v1 u2 v2   R7..R12 sus pasos en x   R13..R15 las texturas
;   R16 LIM   R18 f   R19 columnas que quedan   R25 fila   R26 filas
;   R27 tabla de caras   R28, R29 temporales   R30 fondo
demo_cpu:
    LI    R27, cube_faces
    LI    R1, job_args
    LOAD  R18, R1, 8                        ; f
    LOAD  R13, R27, 0
    LOAD  R14, R27, 32
    LOAD  R15, R27, 64                      ; texturas
    LOAD  R7, R27, 12
    LOAD  R8, R27, 16
    LOAD  R9, R27, 44
    LOAD  R10, R27, 48
    LOAD  R11, R27, 76
    LOAD  R12, R27, 80                      ; pasos en x
    LI    R16, CUBE_LIM
    LI    R30, CUBE_BG
    MOVI  R26, CUBE_ROWS
    MOVI  R25, 0
cube_cpu_row:
    LOAD  R28, R27, 20
    MUL   R28, R25, R28
    LOAD  R1, R27, 4
    ADD   R1, R1, R28
    LOAD  R28, R27, 24
    MUL   R28, R25, R28
    LOAD  R2, R27, 8
    ADD   R2, R2, R28
    LOAD  R28, R27, 52
    MUL   R28, R25, R28
    LOAD  R3, R27, 36
    ADD   R3, R3, R28
    LOAD  R28, R27, 56
    MUL   R28, R25, R28
    LOAD  R4, R27, 40
    ADD   R4, R4, R28
    LOAD  R28, R27, 84
    MUL   R28, R25, R28
    LOAD  R5, R27, 68
    ADD   R5, R5, R28
    LOAD  R28, R27, 88
    MUL   R28, R25, R28
    LOAD  R6, R27, 72
    ADD   R6, R6, R28
    MOVI  R19, CUBE_COLS
cube_cpu_cell:
    BGEU  R1, R16, cube_cpu_m0
    BGEU  R2, R16, cube_cpu_m0
    ADDI  R28, R2, -256
    ADD   R28, R28, R28
    ANDI  R28, R28, 0x3F00
    ADDI  R29, R1, -256
    SHRI  R29, R29, 5
    ANDI  R29, R29, 0xFC
    ADD   R28, R28, R29
    ADD   R28, R28, R13
    LOAD  R29, R28, 0
    BRA   cube_cpu_put
cube_cpu_m0:
    BGEU  R3, R16, cube_cpu_m1
    BGEU  R4, R16, cube_cpu_m1
    ADDI  R28, R4, -256
    ADD   R28, R28, R28
    ANDI  R28, R28, 0x3F00
    ADDI  R29, R3, -256
    SHRI  R29, R29, 5
    ANDI  R29, R29, 0xFC
    ADD   R28, R28, R29
    ADD   R28, R28, R14
    LOAD  R29, R28, 0
    BRA   cube_cpu_put
cube_cpu_m1:
    BGEU  R5, R16, cube_cpu_m2
    BGEU  R6, R16, cube_cpu_m2
    ADDI  R28, R6, -256
    ADD   R28, R28, R28
    ANDI  R28, R28, 0x3F00
    ADDI  R29, R5, -256
    SHRI  R29, R29, 5
    ANDI  R29, R29, 0xFC
    ADD   R28, R28, R29
    ADD   R28, R28, R15
    LOAD  R29, R28, 0
    BRA   cube_cpu_put
cube_cpu_m2:
    ADDI  R29, R30, 0                       ; fondo
cube_cpu_put:
    STORE R29, R18, 0
    STORE R29, R18, 640
    ADD   R1, R1, R7
    ADD   R2, R2, R8
    ADD   R3, R3, R9
    ADD   R4, R4, R10
    ADD   R5, R5, R11
    ADD   R6, R6, R12
    ADDI  R18, R18, 4
    ADDI  R19, R19, -1
    BNE   R19, R0, cube_cpu_cell
    ADDI  R18, R18, 640                     ; la segunda línea de esta fila ya está
    ADDI  R25, R25, 1
    BLT   R25, R26, cube_cpu_row
    RET

; ---- método 1: la GPU ingenua, un hilo por fila ----
;   R2 warp lógico  R3 lane  R4 nwarps  R5 fb  R6 tabla de caras
;   R7..R12 u0 v0 u1 v1 u2 v2  R13..R18 sus pasos en x  R19..R21 texturas
;   R22 LIM  R23 f  R24 columnas que quedan  R25 y  R26 filas  R27 = 5
;   R28, R29 temporales  R30 fondo  R31 = 1280 / paso entre filas
cube_k_naive:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R31, R1, 4                     ; nlanes
    LOAD     R5, R1, 8
    LI       R6, cube_faces
    LOAD     R19, R6, 0
    LOAD     R20, R6, 32
    LOAD     R21, R6, 64
    LOAD     R13, R6, 12
    LOAD     R14, R6, 16
    LOAD     R15, R6, 44
    LOAD     R16, R6, 48
    LOAD     R17, R6, 76
    LOAD     R18, R6, 80
    LI       R22, CUBE_LIM
    LI       R30, CUBE_BG
    MOVI     R26, CUBE_ROWS
    MOVI     R27, 5
    MUL      R25, R2, R31
    ADD      R25, R25, R3                   ; y = hilo
    MUL      R2, R4, R31                    ; el paso: todos los hilos
cube_n_row:
    BGEU     R25, R26, cube_end
    LOAD     R28, R6, 20
    MUL      R28, R25, R28
    LOAD     R7, R6, 4
    ADD      R7, R7, R28
    LOAD     R28, R6, 24
    MUL      R28, R25, R28
    LOAD     R8, R6, 8
    ADD      R8, R8, R28
    LOAD     R28, R6, 52
    MUL      R28, R25, R28
    LOAD     R9, R6, 36
    ADD      R9, R9, R28
    LOAD     R28, R6, 56
    MUL      R28, R25, R28
    LOAD     R10, R6, 40
    ADD      R10, R10, R28
    LOAD     R28, R6, 84
    MUL      R28, R25, R28
    LOAD     R11, R6, 68
    ADD      R11, R11, R28
    LOAD     R28, R6, 88
    MUL      R28, R25, R28
    LOAD     R12, R6, 72
    ADD      R12, R12, R28
    MOVI     R28, 1280
    MUL      R23, R25, R28
    ADD      R23, R23, R5                   ; f
    MOVI     R24, CUBE_COLS
cube_n_cell:
    SSY      cube_n_done
    BGEU     R7, R22, cube_n_m0
    BGEU     R8, R22, cube_n_m0
    ADDI     R28, R8, -256
    ADD      R28, R28, R28
    ANDI     R28, R28, 0x3F00
    ADDI     R29, R7, -256
    SHR      R29, R29, R27
    ANDI     R29, R29, 0xFC
    ADD      R28, R28, R29
    ADD      R28, R28, R19
    LOAD     R29, R28, 0
    BRA      cube_n_done
cube_n_m0:
    BGEU     R9, R22, cube_n_m1
    BGEU     R10, R22, cube_n_m1
    ADDI     R28, R10, -256
    ADD      R28, R28, R28
    ANDI     R28, R28, 0x3F00
    ADDI     R29, R9, -256
    SHR      R29, R29, R27
    ANDI     R29, R29, 0xFC
    ADD      R28, R28, R29
    ADD      R28, R28, R20
    LOAD     R29, R28, 0
    BRA      cube_n_done
cube_n_m1:
    BGEU     R11, R22, cube_n_m2
    BGEU     R12, R22, cube_n_m2
    ADDI     R28, R12, -256
    ADD      R28, R28, R28
    ANDI     R28, R28, 0x3F00
    ADDI     R29, R11, -256
    SHR      R29, R29, R27
    ANDI     R29, R29, 0xFC
    ADD      R28, R28, R29
    ADD      R28, R28, R21
    LOAD     R29, R28, 0
    BRA      cube_n_done
cube_n_m2:
    ADDI     R29, R30, 0
cube_n_done:
    STORE    R29, R23, 0
    STORE    R29, R23, 640
    ADD      R7, R7, R13
    ADD      R8, R8, R14
    ADD      R9, R9, R15
    ADD      R10, R10, R16
    ADD      R11, R11, R17
    ADD      R12, R12, R18
    ADDI     R23, R23, 4
    ADDI     R24, R24, -1
    BNE      R24, R0, cube_n_cell
    ADD      R25, R25, R2
    BRA      cube_n_row

; ---- método 2: la GPU bien puesta, un warp por fila ----
; Cada lane hace las columnas l, l + 8, l + 16...; R13..R18 son los pasos por vuelta
; (8 columnas): 8 ux, 8 vx de cada cara. R2 = 4 * lane, R31 = 8.
cube_k_good:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 8
    LI       R6, cube_faces
    LOAD     R19, R6, 0
    LOAD     R20, R6, 32
    LOAD     R21, R6, 64
    MOVI     R31, 8
    LOAD     R13, R6, 12
    MUL      R13, R13, R31
    LOAD     R14, R6, 16
    MUL      R14, R14, R31
    LOAD     R15, R6, 44
    MUL      R15, R15, R31
    LOAD     R16, R6, 48
    MUL      R16, R16, R31
    LOAD     R17, R6, 76
    MUL      R17, R17, R31
    LOAD     R18, R6, 80
    MUL      R18, R18, R31
    LI       R22, CUBE_LIM
    LI       R30, CUBE_BG
    MOVI     R26, CUBE_ROWS
    MOVI     R27, 5
    MOVI     R28, 2
    SHL      R2, R3, R28                    ; 4 * lane
    GETLWARP R25                            ; y = warp lógico
cube_g_row:
    BGEU     R25, R26, cube_end
    LOAD     R28, R6, 20
    MUL      R28, R25, R28
    LOAD     R7, R6, 4
    ADD      R7, R7, R28
    LOAD     R28, R6, 12
    MUL      R28, R3, R28
    ADD      R7, R7, R28
    LOAD     R28, R6, 24
    MUL      R28, R25, R28
    LOAD     R8, R6, 8
    ADD      R8, R8, R28
    LOAD     R28, R6, 16
    MUL      R28, R3, R28
    ADD      R8, R8, R28
    LOAD     R28, R6, 52
    MUL      R28, R25, R28
    LOAD     R9, R6, 36
    ADD      R9, R9, R28
    LOAD     R28, R6, 44
    MUL      R28, R3, R28
    ADD      R9, R9, R28
    LOAD     R28, R6, 56
    MUL      R28, R25, R28
    LOAD     R10, R6, 40
    ADD      R10, R10, R28
    LOAD     R28, R6, 48
    MUL      R28, R3, R28
    ADD      R10, R10, R28
    LOAD     R28, R6, 84
    MUL      R28, R25, R28
    LOAD     R11, R6, 68
    ADD      R11, R11, R28
    LOAD     R28, R6, 76
    MUL      R28, R3, R28
    ADD      R11, R11, R28
    LOAD     R28, R6, 88
    MUL      R28, R25, R28
    LOAD     R12, R6, 72
    ADD      R12, R12, R28
    LOAD     R28, R6, 80
    MUL      R28, R3, R28
    ADD      R12, R12, R28
    MOVI     R28, 1280
    MUL      R23, R25, R28
    ADD      R23, R23, R5
    ADD      R23, R23, R2                   ; f + la columna de esta lane
    MOVI     R24, 20                        ; 160 columnas / 8 lanes
cube_g_cell:
    SSY      cube_g_done
    BGEU     R7, R22, cube_g_m0
    BGEU     R8, R22, cube_g_m0
    ADDI     R28, R8, -256
    ADD      R28, R28, R28
    ANDI     R28, R28, 0x3F00
    ADDI     R29, R7, -256
    SHR      R29, R29, R27
    ANDI     R29, R29, 0xFC
    ADD      R28, R28, R29
    ADD      R28, R28, R19
    LOAD     R29, R28, 0
    BRA      cube_g_done
cube_g_m0:
    BGEU     R9, R22, cube_g_m1
    BGEU     R10, R22, cube_g_m1
    ADDI     R28, R10, -256
    ADD      R28, R28, R28
    ANDI     R28, R28, 0x3F00
    ADDI     R29, R9, -256
    SHR      R29, R29, R27
    ANDI     R29, R29, 0xFC
    ADD      R28, R28, R29
    ADD      R28, R28, R20
    LOAD     R29, R28, 0
    BRA      cube_g_done
cube_g_m1:
    BGEU     R11, R22, cube_g_m2
    BGEU     R12, R22, cube_g_m2
    ADDI     R28, R12, -256
    ADD      R28, R28, R28
    ANDI     R28, R28, 0x3F00
    ADDI     R29, R11, -256
    SHR      R29, R29, R27
    ANDI     R29, R29, 0xFC
    ADD      R28, R28, R29
    ADD      R28, R28, R21
    LOAD     R29, R28, 0
    BRA      cube_g_done
cube_g_m2:
    ADDI     R29, R30, 0
cube_g_done:
    STORE    R29, R23, 0
    STORE    R29, R23, 640
    ADD      R7, R7, R13
    ADD      R8, R8, R14
    ADD      R9, R9, R15
    ADD      R10, R10, R16
    ADD      R11, R11, R17
    ADD      R12, R12, R18
    ADDI     R23, R23, 32
    ADDI     R24, R24, -1
    BNE      R24, R0, cube_g_cell
    ADD      R25, R25, R4
    BRA      cube_g_row

cube_end:
    EXIT

; ---- datos ----
race_kernels:
    .word 0, cube_k_naive, cube_k_good
race_pixels:
    .word 0x07E007E0, 0xFD20FD20, 0x07FF07FF    ; colores de la gráfica: verde, naranja, cian
race_cycles:
    .word 0, 0, 0                               ; ciclos del último trabajo de cada método
race_period:
    .word 60
race_shift:
    .word 18                                    ; 262 144 ciclos (3,3 ms) por línea: 32 líneas = 105 ms
cube_pal:                                       ; dos colores por textura
    .word 0xF800, 0xFFFF, 0x7800, 0x8410, 0x07E0, 0xFFE0
    .word 0x03E0, 0x8400, 0x001F, 0x07FF, 0x000F, 0x0410
cube_sin:                                       ; 128 * sin(2 pi k / 64), k = 0..63
    .word 0, 13, 25, 37, 49, 60, 71, 81
    .word 91, 99, 106, 113, 118, 122, 126, 127
    .word 128, 127, 126, 122, 118, 113, 106, 99
    .word 91, 81, 71, 60, 49, 37, 25, 13
    .word 0, -13, -25, -37, -49, -60, -71, -81
    .word -91, -99, -106, -113, -118, -122, -126, -127
    .word -128, -127, -126, -122, -118, -113, -106, -99
    .word -91, -81, -71, -60, -49, -37, -25, -13
cube_m:
    .space 36                                   ; la matriz R, 9 palabras
cube_faces:
    .space 96                                   ; 3 caras de 32 bytes
job_args:
    .space 32
