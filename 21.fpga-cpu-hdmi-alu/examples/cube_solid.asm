; ============================================================
; cube_solid.asm - cubo solido con descarte de caras traseras
;
; Conserva la transformacion Q16.16 y la perspectiva de cube.asm. Cada una de
; las seis caras se descarta con el area orientada de su primer triangulo. Las
; caras visibles se dividen en dos triangulos y se rellenan con tres funciones
; de borde incrementales: solo el primer pixel usa multiplicaciones; avanzar
; un pixel o una fila son sumas/restas.
;
; El cubo es convexo. Tras descartar las caras traseras, las caras visibles no
; se ocultan entre si (solo comparten aristas), por lo que no hace falta z-buffer.
; ============================================================

start:
    MOVHI R2, 0x8000

    MOVHI R28, 0x0100
    STORE R28, R2, 0           ; FB_FRONT = 0x01000000
    MOVHI R28, 0x0102
    ORI   R28, R28, 0x5800
    STORE R28, R2, 4           ; FB_BACK  = 0x01025800

    MOVI  R28, 2
    STORE R28, R2, 24          ; VIDEO_CTRL = SCANOUT

    MOVI  R24, 640             ; stride en bytes para putpixel
    MOVI  R26, 0               ; angulo X
    MOVI  R27, 0               ; angulo Y

    ; Limpiar los dos buffers una vez. Despues cada frame solo limpia la caja.
    MOVHI R3, 0x0100
    MOVHI R28, 0x0104
    ORI   R28, R28, 0xB000
clear_once:
    STORE R0, R3, 0
    ADDI  R3, R3, 4
    BLTU  R3, R28, clear_once

frame:
    LOAD  R1, R2, 4

    ; Caja [32,288) x [8,232), igual que cube.asm.
    MOVI  R28, 5184
    ADD   R3, R1, R28
    MOVI  R19, 224
clear_row:
    ADDI  R28, R3, 0
    MOVI  R29, 128
clear_word:
    STORE R0, R28, 0
    ADDI  R28, R28, 4
    ADDI  R29, R29, -1
    BNE   R29, R0, clear_word
    ADD   R3, R3, R24
    ADDI  R19, R19, -1
    BNE   R19, R0, clear_row

    ; Senos y cosenos.
    MOVI  R7, sin_table
    SHLI  R28, R26, 2
    ADD   R28, R7, R28
    LOAD  R20, R28, 0
    ADDI  R28, R26, 64
    ANDI  R28, R28, 255
    SHLI  R28, R28, 2
    ADD   R28, R7, R28
    LOAD  R21, R28, 0

    SHLI  R28, R27, 2
    ADD   R28, R7, R28
    LOAD  R22, R28, 0
    ADDI  R28, R27, 64
    ANDI  R28, R28, 255
    SHLI  R28, R28, 2
    ADD   R28, R7, R28
    LOAD  R23, R28, 0

    ; Rotar y proyectar los ocho vertices a 0x00100000.
    MOVI  R3, vertices
    MOVHI R29, 0x0010
    MOVI  R19, 8
    MOVI  R13, 140
    MOVHI R14, 0x0003
vertex_loop:
    LOAD  R4, R3, 0
    LOAD  R5, R3, 4
    LOAD  R6, R3, 8

    MULFX R7,  R5, R21
    MULFX R8,  R6, R20
    SUB   R7,  R7, R8          ; y1
    MULFX R8,  R5, R20
    MULFX R28, R6, R21
    ADD   R8,  R8, R28         ; z1
    MULFX R9,  R4, R23
    MULFX R28, R8, R22
    ADD   R9,  R9, R28         ; x2
    MULFX R10, R8, R23
    MULFX R28, R4, R22
    SUB   R10, R10, R28        ; z2

    SARI  R9, R9, 8
    SARI  R7, R7, 8
    ADD   R10, R10, R14
    SARI  R10, R10, 8
    MUL   R11, R9, R13
    DIV   R11, R11, R10
    ADDI  R11, R11, 160
    MUL   R12, R7, R13
    DIV   R12, R12, R10
    ADDI  R12, R12, 120

    STORE R11, R29, 0
    STORE R12, R29, 4
    ADDI  R3, R3, 12
    ADDI  R29, R29, 8
    ADDI  R19, R19, -1
    BNE   R19, R0, vertex_loop

    ; Cada cara: cuatro offsets de puntos proyectados y un color RGB565.
    MOVI  R3, faces
    MOVI  R19, 6
face_loop:
    ; Primer triangulo (v0,v1,v2), que tambien decide el culling.
    MOVHI R28, 0x0010
    LOAD  R29, R3, 0
    ADD   R29, R28, R29
    LOAD  R9, R29, 0
    LOAD  R10, R29, 4
    LOAD  R29, R3, 4
    ADD   R29, R28, R29
    LOAD  R11, R29, 0
    LOAD  R12, R29, 4
    LOAD  R29, R3, 8
    ADD   R29, R28, R29
    LOAD  R13, R29, 0
    LOAD  R14, R29, 4

    ; area = (x1-x0)*(y2-y0) - (y1-y0)*(x2-x0)
    SUB   R15, R11, R9
    SUB   R16, R14, R10
    MUL   R17, R15, R16
    SUB   R15, R12, R10
    SUB   R16, R13, R9
    MUL   R18, R15, R16
    SUB   R17, R17, R18
    BGE   R0, R17, face_done   ; area <= 0: cara trasera o de canto

    LOAD  R6, R3, 16
    JAL   R31, fill_triangle

    ; Segundo triangulo (v0,v2,v3). La rutina destruye sus entradas: recargar.
    MOVHI R28, 0x0010
    LOAD  R29, R3, 0
    ADD   R29, R28, R29
    LOAD  R9, R29, 0
    LOAD  R10, R29, 4
    LOAD  R29, R3, 8
    ADD   R29, R28, R29
    LOAD  R11, R29, 0
    LOAD  R12, R29, 4
    LOAD  R29, R3, 12
    ADD   R29, R28, R29
    LOAD  R13, R29, 0
    LOAD  R14, R29, 4
    LOAD  R6, R3, 16
    JAL   R31, fill_triangle

face_done:
    ADDI  R3, R3, 20
    ADDI  R19, R19, -1
    BNE   R19, R0, face_loop

    MOVI  R25, 1
    STORE R25, R2, 8
wait_swap:
    LOAD  R28, R2, 8
    BNE   R28, R0, wait_swap

    ADDI  R26, R26, 1
    ANDI  R26, R26, 255
    ADDI  R27, R27, 3
    ANDI  R27, R27, 255
    BRA   frame

; ---------------------------------------------------------------------------
; fill_triangle
; Entrada: R9=x0 R10=y0 R11=x1 R12=y1 R13=x2 R14=y2 R6=color.
; Requiere R1=FB_BACK y R24=640. El triangulo llega con area positiva.
; Destruye R4,R5,R7-R18,R20-R23,R25,R28-R30. Conserva R3,R19,R24,R26,R27,R31.
; ---------------------------------------------------------------------------
fill_triangle:
    ; Caja del triangulo.
    ADDI  R15, R9, 0
    ADDI  R16, R9, 0
    ADDI  R17, R10, 0
    ADDI  R18, R10, 0
    BGE   R11, R15, @minx1_done
    ADDI  R15, R11, 0
@minx1_done:
    BGE   R13, R15, @minx2_done
    ADDI  R15, R13, 0
@minx2_done:
    BGE   R16, R11, @maxx1_done
    ADDI  R16, R11, 0
@maxx1_done:
    BGE   R16, R13, @maxx2_done
    ADDI  R16, R13, 0
@maxx2_done:
    BGE   R12, R17, @miny1_done
    ADDI  R17, R12, 0
@miny1_done:
    BGE   R14, R17, @miny2_done
    ADDI  R17, R14, 0
@miny2_done:
    BGE   R18, R12, @maxy1_done
    ADDI  R18, R12, 0
@maxy1_done:
    BGE   R18, R14, @maxy2_done
    ADDI  R18, R14, 0
@maxy2_done:

    ; Coeficientes dx,dy de las tres aristas.
    SUB   R20, R11, R9         ; dx01
    SUB   R21, R12, R10        ; dy01
    SUB   R22, R13, R11        ; dx12
    SUB   R23, R14, R12        ; dy12
    SUB   R25, R9, R13         ; dx20
    SUB   R28, R10, R14        ; dy20

    ; E = dx*(y-ya) - dy*(x-xa), evaluada en (minx,miny).
    SUB   R4, R15, R9
    SUB   R5, R17, R10
    MUL   R7, R20, R5
    MUL   R30, R21, R4
    SUB   R7, R7, R30          ; E01 inicial

    SUB   R4, R15, R11
    SUB   R5, R17, R12
    MUL   R8, R22, R5
    MUL   R30, R23, R4
    SUB   R8, R8, R30          ; E12 inicial

    SUB   R4, R15, R13
    SUB   R5, R17, R14
    MUL   R29, R25, R5
    MUL   R30, R28, R4
    SUB   R29, R29, R30        ; E20 inicial

    ; R9-R11 guardan los valores al principio de cada fila.
    ADDI  R9, R7, 0
    ADDI  R10, R8, 0
    ADDI  R11, R29, 0
    ADDI  R5, R17, 0
@tri_row:
    ADDI  R4, R15, 0
    ADDI  R12, R9, 0
    ADDI  R13, R10, 0
    ADDI  R14, R11, 0
@tri_pixel:
    BLT   R12, R0, @tri_skip
    BLT   R13, R0, @tri_skip
    BLT   R14, R0, @tri_skip
    JAL   R30, putpixel
@tri_skip:
    ; Al avanzar x: E += -dy.
    SUB   R12, R12, R21
    SUB   R13, R13, R23
    SUB   R14, R14, R28
    ADDI  R4, R4, 1
    BGE   R16, R4, @tri_pixel

    ; Al avanzar y: E_fila += dx.
    ADD   R9, R9, R20
    ADD   R10, R10, R22
    ADD   R11, R11, R25
    ADDI  R5, R5, 1
    BGE   R18, R5, @tri_row
    RET

    .include "putpixel.inc"

    .rodata

vertices:
    .word -65536, -65536, -65536
    .word  65536, -65536, -65536
    .word -65536,  65536, -65536
    .word  65536,  65536, -65536
    .word -65536, -65536,  65536
    .word  65536, -65536,  65536
    .word -65536,  65536,  65536
    .word  65536,  65536,  65536

; Cuatro vertices en orden y color. Los indices ya son offsets de 8 bytes.
; El orden esta elegido para que una cara visible tenga area positiva en la
; pantalla (el eje Y de pantalla crece hacia abajo).
faces:
    .word  0,  8, 24, 16, 0xF800       ; z- rojo
    .word 32, 48, 56, 40, 0x001F       ; z+ azul
    .word  0, 32, 40,  8, 0xFFE0       ; y- amarillo
    .word 16, 24, 56, 48, 0x07E0       ; y+ verde
    .word  0, 16, 48, 32, 0x07FF       ; x- cyan
    .word  8, 40, 56, 24, 0xF81F       ; x+ magenta

    .include "sin256.inc"
