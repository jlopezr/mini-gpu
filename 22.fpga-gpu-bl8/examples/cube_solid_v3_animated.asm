; Cubo solido animado para MiniGPU, con rasterizador paralelo medible.
;
; Recorre 64 orientaciones generadas con la misma rotacion Q16.16, perspectiva
; y back-face culling de cube_solid.asm. Cada frame contiene seis descriptores
; (hasta tres caras visibles, dos triangulos por cara) en forma A*x+B*y+C.
;
; Cada uno de los 64 hilos posee 600 palabras RGB565: tid, tid+64, ... Los ocho
; lanes de un warp escriben palabras consecutivas y la LSU BL8 las coalesce.
; Cada palabra contiene dos pixeles; se evalua el izquierdo y el derecho antes
; de hacer un unico STORE de 32 bits. Se escribe tambien el fondo, por lo que no
; hace falta una pasada de borrado.

        GETTID R1
        MOVHI R30, 0x8000
        MOVI  R20, 160             ; palabras por fila
        MOVHI R10, 0xFFFF          ; mascara de la mitad alta

        ; Configuracion de video, solo el hilo global 0.
        SSY   video_ready
        BNE   R1, R0, video_ready
        MOVHI R27, 0x0010
        STORE R27, R30, 0          ; FB_FRONT
        MOVHI R27, 0x0014
        STORE R27, R30, 4          ; FB_BACK
        MOVI  R27, 2
        STORE R27, R30, 24         ; SCANOUT
video_ready:
        BAR
        MOVI  R31, cube_frames

        ; Limpiar los dos buffers una sola vez. Cada hilo borra 1200 palabras:
        ; 2 buffers * 38400 palabras / 64 hilos.
        ADD   R3, R1, R0
        MOVI  R6, 1200
        MOVHI R8, 0x0010
        MOVHI R9, 0x0014
clear_loop:
        ADD   R7, R3, R3
        ADD   R7, R7, R7
        ADD   R11, R8, R7
        STORE R0, R11, 0
        ADD   R11, R9, R7
        STORE R0, R11, 0
        ADDI  R3, R3, 64
        ADDI  R6, R6, -1
        BNE   R6, R0, clear_loop
        BAR

frame_loop:
        LOAD  R19, R30, 4          ; buffer trasero actual
        ; Caja del cubo: x=32..287, y=8..231. Son 128*224=28672 palabras,
        ; exactamente 448 por hilo. R3 es x local en palabras y R5 el indice
        ; global dentro del framebuffer.
        ADD   R3, R1, R0
        MOVI  R4, 8
        MOVI  R5, 1296             ; 8*160 + 16
        ADD   R5, R5, R1
        MOVI  R6, 448

word_loop:
        ADDI  R7, R3, 16
        ADD   R7, R7, R7           ; x del pixel izquierdo
        MOVI  R11, 0               ; dos pixeles negros inicialmente
        ADD   R12, R31, R0
        MOVI  R13, 6

triangle_loop:
        ; Tres aristas E=A*x+B*y+C y color duplicado en las dos mitades.
        LOAD  R14, R12, 0
        LOAD  R15, R12, 4
        LOAD  R16, R12, 8
        LOAD  R17, R12, 12
        LOAD  R18, R12, 16
        LOAD  R21, R12, 20
        LOAD  R22, R12, 24
        LOAD  R23, R12, 28
        LOAD  R24, R12, 32
        LOAD  R25, R12, 36

        ; Pixel izquierdo. Las tres comparaciones forman una sola region SIMT.
        MUL   R26, R14, R7
        MUL   R27, R15, R4
        ADD   R26, R26, R27
        ADD   R26, R26, R16
        MUL   R28, R17, R7
        MUL   R29, R18, R4
        ADD   R28, R28, R29
        ADD   R28, R28, R21
        MUL   R2, R22, R7
        MUL   R9, R23, R4
        ADD   R2, R2, R9
        ADD   R2, R2, R24
        SSY   left_done
        BLT   R26, R0, left_done
        BLT   R28, R0, left_done
        BLT   R2, R0, left_done
        AND   R11, R11, R10        ; conservar pixel derecho
        ANDI  R9, R25, 0xFFFF
        OR    R11, R11, R9
left_done:

        ; Al mover un pixel a la derecha cada borde suma A.
        ADD   R26, R26, R14
        ADD   R28, R28, R17
        ADD   R2, R2, R22
        SSY   right_done
        BLT   R26, R0, right_done
        BLT   R28, R0, right_done
        BLT   R2, R0, right_done
        ANDI  R11, R11, 0xFFFF     ; conservar pixel izquierdo
        AND   R9, R25, R10
        OR    R11, R11, R9
right_done:
        ADDI  R12, R12, 40
        ADDI  R13, R13, -1
        BNE   R13, R0, triangle_loop

        ; direccion = FB_BACK + 4*indice_de_palabra
        ADD   R8, R5, R5
        ADD   R8, R8, R8
        ADD   R8, R19, R8
        STORE R11, R8, 0

        ADDI  R5, R5, 64
        ADDI  R3, R3, 64
        MOVI  R8, 128
        BLT   R3, R8, no_wrap
        SUB   R3, R3, R8
        ADDI  R5, R5, 32           ; salto entre filas: stride 160, caja 128
        ADDI  R4, R4, 1
no_wrap:
        ADDI  R6, R6, -1
        BNE   R6, R0, word_loop

        BAR
        SSY   swapped
        BNE   R1, R0, swapped
        MOVI  R15, 1
        STORE R15, R30, 8
poll_swap:
        LOAD  R15, R30, 8
        ANDI  R15, R15, 1
        BNE   R15, R0, poll_swap
swapped:
        BAR
        ADDI  R31, R31, 240        ; 6 triangulos * 10 palabras * 4 bytes
        MOVI  R27, cube_frames_end
        BLT   R31, R27, frame_ready
        MOVI  R31, cube_frames
frame_ready:
        BRA   frame_loop

        .rodata
        .include "cube_solid_frames_v3.inc"
