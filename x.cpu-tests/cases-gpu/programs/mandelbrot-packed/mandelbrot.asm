; ============================================================
; Mandelbrot para MiniGPU - framebuffer de 1 byte por pixel
; Q16.16
;
; Version A del plan de byte-framebuffer.md: el empaquetado se
; hace en software, sin LOADB/STOREB. Cada lane calcula 4 pixeles
; consecutivos y los junta en una sola palabra de 32 bits.
;
; Imagen: 320 x 240 = 76800 pixeles
; MAX_ITER = 256, saturado a 255 para que quepa en un byte
; Framebuffer: 76800 bytes = 0x12C00, base 0x4000, fin 0x16C00
;   (cabe en los 128 KiB de gpu_bram: 0x00000-0x1FFFF)
;
; ------------------------------------------------------------
; Por que grupos de 4 y no un pixel por lane
; ------------------------------------------------------------
;
; El banco de BRAM se elige con addr[4:2], asi que palabras
; consecutivas caen en bancos distintos y el LSU las sirve en una
; sola oleada. Bytes consecutivos caerian en solo 2 bancos y
; costarian 4 oleadas.
;
; Aqui cada lane escribe UNA palabra por grupo. thread_id es
; warp*8 + lane, luego los 8 lanes de un warp tienen grupos
; consecutivos g..g+7, con direcciones base+4g..base+4(g+7) y por
; tanto addr[4:2] = 0..7: los ocho bancos, una oleada.
;
; 19200 grupos / 64 hilos = 300 iteraciones exactas por lane, sin
; cola divergente.
;
; ------------------------------------------------------------
; Registros
; ------------------------------------------------------------
;
; R0  = 0                       (constante, R0 no es cero por hardware)
; R1  = WIDTH = 320
; R2  = WIDTH-1 = 319
; R3  = NUM_GROUPS = 19200
; R4  = MAX_ITER = 256
; R5  = X_MIN                   -2.0
; R6  = X_RANGE                  3.0
; R7  = Y_MAX                    1.125
; R8  = Y_RANGE                  2.25
; R9  = 4.0
; R10 = framebuffer base
; R11 = grupo (4 pixeles)
; R12 = x
; R13 = y
; R14 = cx
; R15 = cy
; R16 = zx
; R17 = zy
; R18 = iteracion
; R19 = zx2
; R20 = zy2
; R21 = magnitud
; R22 = new_zy
; R23 = new_zx
; R24 = temporal
; R25 = 8                       (desplazamiento de byte)
; R26 = k, indice dentro del grupo (3..0)
; R27 = palabra empaquetada
; R28 = pixel absoluto
; R29 = 2                       (desplazamiento grupo -> byte)
; R30 = direccion de escritura
; R31 = HEIGHT-1 = 239
; ============================================================


start:

    MOVI  R0, 0

    MOVI  R1, 320
    MOVI  R2, 319
    MOVI  R31, 239

    ; 19200 grupos de 4 pixeles = 76800 pixeles
    MOVI  R3, 19200

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

    ; framebuffer = 0x00004000
    MOVI  R10, 0x4000

    ; constantes de desplazamiento
    MOVI  R25, 8
    MOVI  R29, 2


    ; --------------------------------------------------------
    ; Cada lane arranca en su propio grupo: 0..63
    ; --------------------------------------------------------

    GETTID R11


group_loop:

    ; Este lane ya no tiene mas grupos
    BGE   R11, R3, thread_done

    ; Empezamos por el byte alto: k = 3, y vamos bajando.
    ; packed = (packed << 8) | iter deja el pixel k=0 en el byte
    ; bajo, que es el orden little-endian que espera el visor.
    MOVI  R27, 0
    MOVI  R26, 3


pack_loop:

    ; pixel = grupo*4 + k
    SHL   R28, R11, R29
    ADD   R28, R28, R26


    ; ========================================================
    ; pixel -> x,y
    ;
    ; y = pixel / 320
    ; x = pixel - y*320
    ; ========================================================

    DIV   R13, R28, R1

    MUL   R24, R13, R1
    SUB   R12, R28, R24


    ; ========================================================
    ; cx = X_MIN + x*X_RANGE/319
    ; ========================================================

    MUL   R24, R12, R6
    DIV   R24, R24, R2
    ADD   R14, R5, R24


    ; ========================================================
    ; cy = Y_MAX - y*Y_RANGE/239
    ; ========================================================

    MUL   R24, R13, R8
    DIV   R24, R24, R31
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

    ; Una region por pixel, abierta antes de entrar al bucle.
    ; Las lanes que escapan esperan en mandel_done sin reservar PATH.
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

    ; Aqui el warp ha reconvergido.
    ; Cada lane conserva su R18 particular.


    ; ========================================================
    ; Saturar 256 -> 255 sin ramificar
    ;
    ; iter esta en 0..256, asi que iter>>8 vale 1 solo cuando
    ; iter==256. Restarlo deja 255 y no toca ningun otro valor.
    ; Una rama aqui divergiria el warp; esto no.
    ; ========================================================

    SHR   R24, R18, R25
    SUB   R18, R18, R24


    ; ========================================================
    ; packed = (packed << 8) | iter
    ; ========================================================

    SHL   R27, R27, R25
    OR    R27, R27, R18


    ; k-- ; repetir mientras k >= 0
    ADDI  R26, R26, -1
    BGE   R26, R0, pack_loop


    ; ========================================================
    ; framebuffer_word[grupo] = packed
    ;
    ; Una sola escritura de palabra alineada por grupo: los 8
    ; lanes del warp tocan 8 bancos distintos.
    ; ========================================================

    SHL   R30, R11, R29
    ADD   R30, R10, R30

    STORE R27, R30, 0


    ; ========================================================
    ; Siguiente grupo asignado al mismo lane
    ; ========================================================

    ADDI  R11, R11, 64

    BRA   group_loop


thread_done:

    EXIT
