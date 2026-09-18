; Cubo solido animado para MiniGPU, con rasterizador paralelo medible.
;
; Recorre 64 orientaciones generadas con la misma rotacion Q16.16, perspectiva
; y back-face culling de cube_solid.asm. Cada frame contiene seis descriptores
; (hasta tres caras visibles, dos triangulos por cara) en forma A*x+B*y+C.
;
; A diferencia de v3, procesa un triangulo completo antes del siguiente: carga
; su descriptor una vez, recorre solo su caja y actualiza las tres funciones de
; borde con sumas. Cada warp posee filas separadas por 8 y sus ocho lanes
; escriben ocho palabras consecutivas, que la LSU BL8 puede coalescer.

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

        ; Borrar la caja completa antes de pintar los triangulos visibles.
        ADD   R3, R1, R0
        MOVI  R4, 8
        MOVI  R5, 1296             ; 8*160 + 16
        ADD   R5, R5, R1
        MOVI  R6, 448
frame_clear:
        ADD   R8, R5, R5
        ADD   R8, R8, R8
        ADD   R8, R19, R8
        STORE R0, R8, 0
        ADDI  R5, R5, 64
        ADDI  R3, R3, 64
        MOVI  R8, 128
        BLT   R3, R8, clear_no_wrap
        SUB   R3, R3, R8
        ADDI  R5, R5, 32
clear_no_wrap:
        ADDI  R6, R6, -1
        BNE   R6, R0, frame_clear
        BAR

        ; Procesar los seis slots de triangulo en orden. Los inactivos tienen
        ; maxy < miny y se saltan uniformemente.
        ADD   R12, R31, R0
        MOVI  R13, 6
triangle_loop:
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
        LOAD  R26, R12, 40         ; min word, alineada a 8
        LOAD  R28, R12, 44         ; max word, fin de bloque de 8
        LOAD  R29, R12, 48         ; min y
        LOAD  R27, R12, 52         ; max y
        BLT   R27, R29, triangle_done

        ; lane=tid&7, warp=tid>>3. Cada warp empieza en una fila distinta.
        ANDI  R2, R1, 7
        MOVI  R4, 3
        SHR   R3, R1, R4
        ADD   R4, R29, R3          ; y = miny + warp
        BLT   R27, R4, triangle_done
        ADD   R5, R26, R2          ; palabra inicial de esta lane

        ; Numero de bloques de ocho palabras por fila.
        SUB   R6, R28, R26
        ADDI  R6, R6, 1
        MOVI  R8, 3
        SHR   R6, R6, R8

        ; Valores iniciales de los tres bordes en (2*xword,y).
        ADD   R7, R5, R5
        MUL   R2, R14, R7
        MUL   R8, R15, R4
        ADD   R2, R2, R8
        ADD   R2, R2, R16
        MUL   R3, R17, R7
        MUL   R8, R18, R4
        ADD   R3, R3, R8
        ADD   R3, R3, R21
        MUL   R7, R22, R7
        MUL   R8, R23, R4
        ADD   R7, R7, R8
        ADD   R7, R7, R24

        ; Una iteracion avanza 8 palabras = 16 pixeles: step=A*16.
        MOVI  R8, 16
        MUL   R16, R14, R8
        MUL   R21, R17, R8
        MUL   R24, R22, R8

        ; Al acabar una fila, los bordes estan adelantados n*step. Esta delta
        ; los lleva al inicio de la fila que corresponde al mismo warp (+8y).
        MOVI  R8, 8
        MUL   R15, R15, R8
        MUL   R9, R16, R6
        SUB   R15, R15, R9
        MUL   R18, R18, R8
        MUL   R9, R21, R6
        SUB   R18, R18, R9
        MUL   R23, R23, R8
        MUL   R9, R24, R6
        SUB   R23, R23, R9

triangle_row:
        ; Direccion de la primera palabra de esta lane en la fila.
        MOVI  R8, 160
        MUL   R8, R4, R8
        ADD   R8, R8, R5
        ADD   R8, R8, R8
        ADD   R8, R8, R8
        ADD   R8, R19, R8
        ADD   R9, R6, R0

triangle_word:
        LOAD  R11, R8, 0

        ; Pixel izquierdo: los bordes actuales corresponden a 2*xword.
        SSY   left_done
        BLT   R2, R0, left_done
        BLT   R3, R0, left_done
        BLT   R7, R0, left_done
        AND   R11, R11, R10        ; conservar pixel derecho
        ANDI  R29, R25, 0xFFFF
        OR    R11, R11, R29
left_done:

        ; Pixel derecho: E(x+1)=E(x)+A.
        ADD   R29, R2, R14
        SSY   right_done
        BLT   R29, R0, right_done
        ADD   R29, R3, R17
        BLT   R29, R0, right_done
        ADD   R29, R7, R22
        BLT   R29, R0, right_done
        ANDI  R11, R11, 0xFFFF     ; conservar pixel izquierdo
        AND   R29, R25, R10
        OR    R11, R11, R29
right_done:
        STORE R11, R8, 0
        ADD   R2, R2, R16
        ADD   R3, R3, R21
        ADD   R7, R7, R24
        ADDI  R8, R8, 32
        ADDI  R9, R9, -1
        BNE   R9, R0, triangle_word

        ADD   R2, R2, R15
        ADD   R3, R3, R18
        ADD   R7, R7, R23
        ADDI  R4, R4, 8
        BGE   R27, R4, triangle_row

triangle_done:
        BAR
        ADDI  R12, R12, 56
        ADDI  R13, R13, -1
        BNE   R13, R0, triangle_loop

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
        ADDI  R31, R31, 336        ; 6 triangulos * 14 palabras * 4 bytes
        MOVI  R27, cube_frames_end
        BLT   R31, R27, frame_ready
        MOVI  R31, cube_frames
frame_ready:
        BRA   frame_loop

        .rodata
        .include "cube_solid_frames_v4.inc"
