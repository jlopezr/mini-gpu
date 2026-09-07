; ============================================================
; Mandelbrot para MiniGPU
; Q16.16
;
; 8 warps x 8 lanes = 64 threads residentes
; 1 warp ejecutando por ciclo
;
; Cada lane:
;   pixel = GETTID           ; 0..63 inicialmente
;   pixel += 64              ; siguiente trabajo
;
; Imagen: 320 x 240
; MAX_ITER = 256
; ============================================================

; ------------------------------------------------------------
; Registros
; ------------------------------------------------------------
;
; R1  = WIDTH = 320
; R2  = HEIGHT = 240
; R3  = NUM_PIXELS = 76800
; R4  = MAX_ITER = 256
;
; R5  = X_MIN
; R6  = X_RANGE
; R7  = Y_MAX
; R8  = Y_RANGE
; R9  = 4.0 Q16.16
;
; R10 = framebuffer base
;
; R11 = pixel id
; R12 = x
; R13 = y
;
; R14 = cx
; R15 = cy
;
; R16 = zx
; R17 = zy
; R18 = iteration
;
; R19 = zx2
; R20 = zy2
; R21 = magnitude
;
; R22 = new_zy
; R23 = new_zx
;
; R24-R29 = temporales
; R30 = framebuffer address


start:

    MOVI  R1, 320
    MOVI  R2, 240

    ; 76800 = 0x00012C00
    MOVHI R3, 0x0001
    ORI   R3, R3, 0x2C00

    MOVI  R4, 256

    ; X_MIN = -2.0
    MOVHI R5, 0xFFFE
    ORI   R5, R5, 0x0000

    ; X_RANGE = 3.0
    MOVHI R6, 0x0003
    ORI   R6, R6, 0x0000

    ; Y_MAX = 1.125
    MOVHI R7, 0x0001
    ORI   R7, R7, 0x2000

    ; Y_RANGE = 2.25
    MOVHI R8, 0x0002
    ORI   R8, R8, 0x4000

    ; 4.0 Q16.16
    MOVHI R9, 0x0004
    ORI   R9, R9, 0x0000

    ; framebuffer = 0x00100000
    MOVHI R10, 0x0010
    ORI   R10, R10, 0x0000


    ; --------------------------------------------------------
    ; Cada lane obtiene su pixel inicial
    ; GETTID = 0..63
    ; --------------------------------------------------------

    GETTID R11


pixel_loop:

    ; Este lane ya no tiene más píxeles
    BGE   R11, R3, thread_done


    ; ========================================================
    ; pixel -> x,y
    ;
    ; y = pixel / 320
    ; x = pixel - y*320
    ; ========================================================

    DIV   R13, R11, R1

    MUL   R24, R13, R1
    SUB   R12, R11, R24


    ; ========================================================
    ; cx = X_MIN + x*X_RANGE/319
    ; ========================================================

    MUL   R24, R12, R6

    MOVI  R25, 319
    DIV   R24, R24, R25

    ADD   R14, R5, R24


    ; ========================================================
    ; cy = Y_MAX - y*Y_RANGE/239
    ; ========================================================

    MUL   R24, R13, R8

    MOVI  R25, 239
    DIV   R24, R24, R25

    SUB   R15, R7, R24


    ; ========================================================
    ; z = 0
    ; ========================================================

    MOVI  R16, 0
    MOVI  R17, 0
    MOVI  R18, 0


    ; ========================================================
    ; Punto de reconvergencia del bucle Mandelbrot
    ; ========================================================

    SSY   mandel_done


mandel_loop:

    ; iteration >= MAX_ITER
    BGE   R18, R4, mandel_done

    MULFX R19, R16, R16        ; zx2
    MULFX R20, R17, R17        ; zy2

    ADD   R21, R19, R20

    ; zx2 + zy2 >= 4.0
    BGE   R21, R9, mandel_done


    ; new_zy = 2*zx*zy + cy

    MULFX R22, R16, R17
    ADD   R22, R22, R22
    ADD   R22, R22, R15


    ; new_zx = zx2 - zy2 + cx

    SUB   R23, R19, R20
    ADD   R23, R23, R14


    ADDI  R16, R23, 0
    ADDI  R17, R22, 0

    ADDI  R18, R18, 1

    BRA   mandel_loop


mandel_done:

    ; Aquí el warp ha reconvergido.
    ; Cada lane conserva su R18 particular.


    ; ========================================================
    ; framebuffer[pixel] = iteration
    ; ========================================================

    MOVI R24, 2
    SHL  R30, R11, R24
    ADD  R30, R10, R30

    STORE R18, R30, 0


    ; ========================================================
    ; Siguiente píxel asignado al mismo lane
    ; ========================================================

    ADDI  R11, R11, 64

    BRA   pixel_loop


thread_done:

    EXIT
