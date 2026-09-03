; ============================================================
; Mandelbrot para MiniISA v0.1
; Q16.16, CPU escalar
;
; Imagen: 320 x 240
; MAX_ITER = 256
;
; Coordenadas:
;   X_MIN = -2.0       = 0xFFFE0000
;   X_RANGE = 3.0      = 0x00030000
;   Y_MAX =  1.125     = 0x00012000
;   Y_RANGE = 2.25     = 0x00024000
;
; Mapeo:
;   cx = X_MIN + x * X_RANGE / (WIDTH-1)
;   cy = Y_MAX - y * Y_RANGE / (HEIGHT-1)
;
; Framebuffer:
;   1 word de 32 bits por pixel por ahora
;   dirección base = 0x00100000
;
; NOTA:
;   MULFX se usa para la iteración compleja.
;   Para pixel*range necesitamos multiplicación ENTERA.
;   Esta primera versión usa MUL (opcode reservado en la ISA).
; ============================================================

; ------------------------------------------------------------
; Convención de registros
; ------------------------------------------------------------
;
; R1  = x
; R2  = y
; R3  = WIDTH
; R4  = HEIGHT
; R5  = MAX_ITER
; R6  = WIDTH-1
; R7  = HEIGHT-1
;
; R8  = X_MIN
; R9  = X_RANGE
; R10 = Y_MAX
; R11 = Y_RANGE
; R12 = 4.0 Q16.16
;
; R13 = framebuffer pointer
;
; R14 = cx
; R15 = cy
;
; R16 = zx
; R17 = zy
; R18 = iteration
; R19 = zx2
; R20 = zy2
; R21 = temporary / magnitude
; R22 = temporary new_zy
; R23 = temporary new_zx
; R24 = temporary pixel-coordinate arithmetic
;
; ------------------------------------------------------------

start:
    ; WIDTH = 320
    MOVI  R3, 320

    ; HEIGHT = 240
    MOVI  R4, 240

    ; MAX_ITER = 256
    MOVI  R5, 256

    ; WIDTH-1 = 319
    MOVI  R6, 319

    ; HEIGHT-1 = 239
    MOVI  R7, 239

    ; X_MIN = 0xFFFE0000
    MOVHI R8, 0xFFFE
    ORI   R8, R8, 0x0000

    ; X_RANGE = 3.0 = 0x00030000
    MOVHI R9, 0x0003
    ORI   R9, R9, 0x0000

    ; Y_MAX = 1.125 = 0x00012000
    MOVHI R10, 0x0001
    ORI   R10, R10, 0x2000

    ; Y_RANGE = 2.25 = 0x00024000
    MOVHI R11, 0x0002
    ORI   R11, R11, 0x4000

    ; 4.0 = 0x00040000
    MOVHI R12, 0x0004
    ORI   R12, R12, 0x0000

    ; framebuffer = 0x00100000
    MOVHI R13, 0x0010
    ORI   R13, R13, 0x0000

    MOVI  R2, 0                  ; y = 0

y_loop:
    MOVI  R1, 0                  ; x = 0

    ; --------------------------------------------------------
    ; cy = Y_MAX - (y * Y_RANGE) / (HEIGHT-1)
    ;
    ; y es entero, Y_RANGE es Q16.16.
    ; Multiplicar ambos como enteros produce directamente Q16.16
    ; escalado por y, por lo que aquí necesitamos MUL entero,
    ; NO MULFX.
    ; --------------------------------------------------------
    MUL   R24, R2, R11
    DIV   R24, R24, R7
    SUB   R15, R10, R24

x_loop:
    ; --------------------------------------------------------
    ; cx = X_MIN + (x * X_RANGE) / (WIDTH-1)
    ; --------------------------------------------------------
    MUL   R24, R1, R9
    DIV   R24, R24, R6
    ADD   R14, R8, R24

    ; z = 0
    MOVI  R16, 0                 ; zx
    MOVI  R17, 0                 ; zy
    MOVI  R18, 0                 ; iteration

mandel_loop:
    ; if iteration >= MAX_ITER: done
    BGE   R18, R5, mandel_done

    ; zx2 = zx*zx
    MULFX R19, R16, R16

    ; zy2 = zy*zy
    MULFX R20, R17, R17

    ; if zx2 + zy2 >= 4.0: done
    ADD   R21, R19, R20
    BGE   R21, R12, mandel_done

    ; new_zy = 2*zx*zy + cy
    MULFX R22, R16, R17
    ADD   R22, R22, R22
    ADD   R22, R22, R15

    ; new_zx = zx2 - zy2 + cx
    SUB   R23, R19, R20
    ADD   R23, R23, R14

    ; zx = new_zx
    ADDI  R16, R23, 0

    ; zy = new_zy
    ADDI  R17, R22, 0

    ; iteration++
    ADDI  R18, R18, 1

    BRA   mandel_loop

mandel_done:
    ; Guardamos iteration como word de 32 bits.
    STORE R18, R13, 0

    ; framebuffer pointer += 4
    ADDI  R13, R13, 4

    ; x++
    ADDI  R1, R1, 1
    BLT   R1, R3, x_loop

    ; y++
    ADDI  R2, R2, 1
    BLT   R2, R4, y_loop

    HALT
