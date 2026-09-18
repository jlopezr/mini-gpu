; Cubo solido v6: transformacion de vertices en paralelo en un warp.
;
; Las lanes globales 0..7 rotan y proyectan un vertice cada una. Despues la
; lane 0 hace back-face culling y genera los seis descriptores en RAM. Los 64
; hilos reutilizan el rasterizador incremental de v4. No hay tabla de frames.

        GETTID R1
        MOVHI R30, 0x8000
        MOVI  R20, 160
        MOVHI R10, 0xFFFF

        SSY   video_ready
        BNE   R1, R0, video_ready
        MOVHI R27, 0x0010
        STORE R27, R30, 0
        MOVHI R27, 0x0014
        STORE R27, R30, 4
        MOVI  R27, 2
        STORE R27, R30, 24
video_ready:
        BAR

        ; Limpiar los dos buffers una vez.
        ADD   R3, R1, R0
        MOVI  R6, 1200
        MOVHI R8, 0x0010
        MOVHI R9, 0x0014
clear_both:
        ADD   R7, R3, R3
        ADD   R7, R7, R7
        ADD   R11, R8, R7
        STORE R0, R11, 0
        ADD   R11, R9, R7
        STORE R0, R11, 0
        ADDI  R3, R3, 64
        ADDI  R6, R6, -1
        BNE   R6, R0, clear_both
        BAR

frame_loop:
        ; Un warp transforma los ocho vertices: una lane por vertice.
        MOVI  R2, 8
        SSY   vertices_ready
        BGE   R1, R2, vertices_ready

        MOVI  R27, cube_angle
        LOAD  R2, R27, 0          ; a
        MOVI  R3, cube_sine_q14

        ADD   R5, R2, R2
        ADD   R5, R5, R5
        ADD   R5, R3, R5
        LOAD  R6, R5, 0           ; sin(a)
        ADDI  R4, R2, 64
        ANDI  R4, R4, 255
        ADD   R5, R4, R4
        ADD   R5, R5, R5
        ADD   R5, R3, R5
        LOAD  R7, R5, 0           ; cos(a)

        MOVI  R4, 3
        MUL   R8, R2, R4
        ANDI  R8, R8, 255         ; b=3*a
        ADD   R5, R8, R8
        ADD   R5, R5, R5
        ADD   R5, R3, R5
        LOAD  R9, R5, 0           ; sin(b)
        ADDI  R8, R8, 64
        ANDI  R8, R8, 255
        ADD   R5, R8, R8
        ADD   R5, R5, R5
        ADD   R5, R3, R5
        LOAD  R10, R5, 0          ; cos(b)

        MOVI  R11, cube_points
        ADD   R12, R1, R0          ; indice de vertice = lane
        ADD   R5, R12, R12         ; direccion = base + indice*8
        ADD   R5, R5, R5
        ADD   R5, R5, R5
        ADD   R11, R11, R5

        ; Vertices +/-256; los bits del indice eligen x,y,z.
        MOVI  R14, -256
        ANDI  R5, R12, 1
        SSY   vertex_x_ok
        BEQ   R5, R0, vertex_x_ok
        MOVI  R14, 256
vertex_x_ok:
        MOVI  R15, -256
        ANDI  R5, R12, 2
        SSY   vertex_y_ok
        BEQ   R5, R0, vertex_y_ok
        MOVI  R15, 256
vertex_y_ok:
        MOVI  R16, -256
        ANDI  R5, R12, 4
        SSY   vertex_z_ok
        BEQ   R5, R0, vertex_z_ok
        MOVI  R16, 256
vertex_z_ok:
        ; y1=(y*ca-z*sa)>>14; z1=(y*sa+z*ca)>>14.
        MUL   R17, R15, R7
        MUL   R5, R16, R6
        SUB   R17, R17, R5
        MOVI  R5, 14
        SAR   R17, R17, R5
        MUL   R18, R15, R6
        MUL   R5, R16, R7
        ADD   R18, R18, R5
        MOVI  R5, 14
        SAR   R18, R18, R5
        ; x2=(x*cb+z1*sb)>>14; z2=(z1*cb-x*sb)>>14.
        MUL   R19, R14, R10
        MUL   R5, R18, R9
        ADD   R19, R19, R5
        MOVI  R5, 14
        SAR   R19, R19, R5
        MUL   R21, R18, R10
        MUL   R5, R14, R9
        SUB   R21, R21, R5
        MOVI  R5, 14
        SAR   R21, R21, R5

        ADDI  R21, R21, 768       ; camara a z=-3
        MOVI  R22, 140
        MUL   R19, R19, R22
        DIV   R19, R19, R21
        ADDI  R19, R19, 160
        MUL   R17, R17, R22
        DIV   R17, R17, R21
        ADDI  R17, R17, 120
        STORE R19, R11, 0
        STORE R17, R11, 4

vertices_ready:
        BAR

        ; El setup sigue serial en v6 para aislar la mejora de los vertices.
        SSY   geometry_ready
        BNE   R1, R0, geometry_ready

        ; Recorrer los 12 triangulos. Solo se emiten los orientados al frente.
        MOVI  R2, cube_triangles
        MOVI  R3, 12
        MOVI  R4, cube_descriptors
        MOVI  R5, 0               ; numero emitido
triangle_setup_loop:
        LOAD  R6, R2, 0
        LOAD  R7, R2, 4
        LOAD  R8, R2, 8
        LOAD  R9, R2, 12          ; color RGB565
        MOVI  R10, cube_points
        ADD   R11, R6, R6
        ADD   R11, R11, R11
        ADD   R11, R11, R11
        ADD   R11, R10, R11
        LOAD  R12, R11, 0         ; x0
        LOAD  R13, R11, 4         ; y0
        ADD   R11, R7, R7
        ADD   R11, R11, R11
        ADD   R11, R11, R11
        ADD   R11, R10, R11
        LOAD  R14, R11, 0         ; x1
        LOAD  R15, R11, 4         ; y1
        ADD   R11, R8, R8
        ADD   R11, R11, R11
        ADD   R11, R11, R11
        ADD   R11, R10, R11
        LOAD  R16, R11, 0         ; x2
        LOAD  R17, R11, 4         ; y2

        SUB   R18, R14, R12
        SUB   R19, R17, R13
        MUL   R18, R18, R19
        SUB   R19, R15, R13
        SUB   R21, R16, R12
        MUL   R19, R19, R21
        SUB   R18, R18, R19       ; area proyectada
        BGE   R0, R18, triangle_setup_next

        ; E0 para p0->p1.
        SUB   R18, R13, R15
        SUB   R19, R14, R12
        SUB   R20, R15, R13
        MUL   R21, R20, R12
        MUL   R22, R19, R13
        SUB   R20, R21, R22
        STORE R18, R4, 0
        STORE R19, R4, 4
        STORE R20, R4, 8
        ; E1 para p1->p2.
        SUB   R18, R15, R17
        SUB   R19, R16, R14
        SUB   R20, R17, R15
        MUL   R21, R20, R14
        MUL   R22, R19, R15
        SUB   R20, R21, R22
        STORE R18, R4, 12
        STORE R19, R4, 16
        STORE R20, R4, 20
        ; E2 para p2->p0.
        SUB   R18, R17, R13
        SUB   R19, R12, R16
        SUB   R20, R13, R17
        MUL   R21, R20, R16
        MUL   R22, R19, R17
        SUB   R20, R21, R22
        STORE R18, R4, 24
        STORE R19, R4, 28
        STORE R20, R4, 32
        MOVHI R11, 1
        MUL   R11, R9, R11
        OR    R11, R11, R9
        STORE R11, R4, 36

        ; Bounding box y limites en palabras, alineada a ocho palabras.
        ADD   R18, R12, R0        ; min x
        ADD   R19, R12, R0        ; max x
        ADD   R20, R13, R0        ; min y
        ADD   R21, R13, R0        ; max y
        BGE   R14, R18, minx1_ok
        ADD   R18, R14, R0
minx1_ok:
        BGE   R19, R14, maxx1_ok
        ADD   R19, R14, R0
maxx1_ok:
        BGE   R16, R18, minx2_ok
        ADD   R18, R16, R0
minx2_ok:
        BGE   R19, R16, maxx2_ok
        ADD   R19, R16, R0
maxx2_ok:
        BGE   R15, R20, miny1_ok
        ADD   R20, R15, R0
miny1_ok:
        BGE   R21, R15, maxy1_ok
        ADD   R21, R15, R0
maxy1_ok:
        BGE   R17, R20, miny2_ok
        ADD   R20, R17, R0
miny2_ok:
        BGE   R21, R17, maxy2_ok
        ADD   R21, R17, R0
maxy2_ok:
        MOVI  R22, 1
        SHR   R18, R18, R22
        ANDI  R18, R18, 0xFFF8
        SHR   R19, R19, R22
        ORI   R19, R19, 7
        STORE R18, R4, 40
        STORE R19, R4, 44
        STORE R20, R4, 48
        STORE R21, R4, 52
        ADDI  R4, R4, 56
        ADDI  R5, R5, 1
triangle_setup_next:
        ADDI  R2, R2, 16
        ADDI  R3, R3, -1
        BNE   R3, R0, triangle_setup_loop

        ; Robustez para vistas degeneradas: completar hasta seis slots.
        MOVI  R6, 6
inactive_loop:
        BGE   R5, R6, descriptors_done
        MOVI  R7, -1
        STORE R0, R4, 0
        STORE R0, R4, 4
        STORE R7, R4, 8
        STORE R0, R4, 12
        STORE R0, R4, 16
        STORE R7, R4, 20
        STORE R0, R4, 24
        STORE R0, R4, 28
        STORE R7, R4, 32
        STORE R0, R4, 36
        STORE R0, R4, 40
        MOVI  R8, 7
        STORE R8, R4, 44
        MOVI  R8, 1
        STORE R8, R4, 48
        STORE R0, R4, 52
        ADDI  R4, R4, 56
        ADDI  R5, R5, 1
        BRA   inactive_loop
descriptors_done:
        MOVI  R27, cube_angle
        LOAD  R2, R27, 0
        ADDI  R2, R2, 4
        ANDI  R2, R2, 255
        STORE R2, R27, 0
geometry_ready:
        BAR
        MOVHI R10, 0xFFFF         ; geometria usa R10; restaurar mascara RGB565

        LOAD  R19, R30, 4
        ADD   R3, R1, R0
        MOVI  R5, 1296
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
        BLT   R3, R8, frame_clear_no_wrap
        SUB   R3, R3, R8
        ADDI  R5, R5, 32
frame_clear_no_wrap:
        ADDI  R6, R6, -1
        BNE   R6, R0, frame_clear
        BAR

        MOVI  R12, cube_descriptors
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
        LOAD  R26, R12, 40
        LOAD  R28, R12, 44
        LOAD  R29, R12, 48
        LOAD  R27, R12, 52
        BLT   R27, R29, triangle_done

        ANDI  R2, R1, 7
        MOVI  R8, 3
        SHR   R3, R1, R8
        ADD   R4, R29, R3
        BLT   R27, R4, triangle_done
        ADD   R5, R26, R2
        SUB   R6, R28, R26
        ADDI  R6, R6, 1
        MOVI  R8, 3
        SHR   R6, R6, R8

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
        MOVI  R8, 16
        MUL   R16, R14, R8
        MUL   R21, R17, R8
        MUL   R24, R22, R8
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
        MOVI  R8, 160
        MUL   R8, R4, R8
        ADD   R8, R8, R5
        ADD   R8, R8, R8
        ADD   R8, R8, R8
        ADD   R8, R19, R8
        ADD   R9, R6, R0
triangle_word:
        LOAD  R11, R8, 0
        SSY   left_done
        BLT   R2, R0, left_done
        BLT   R3, R0, left_done
        BLT   R7, R0, left_done
        AND   R11, R11, R10
        ANDI  R29, R25, 0xFFFF
        OR    R11, R11, R29
left_done:
        ADD   R29, R2, R14
        SSY   right_done
        BLT   R29, R0, right_done
        ADD   R29, R3, R17
        BLT   R29, R0, right_done
        ADD   R29, R7, R22
        BLT   R29, R0, right_done
        ANDI  R11, R11, 0xFFFF
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
        BRA   frame_loop

        .rodata
cube_triangles:
        .word 0,1,3,0xF800, 0,3,2,0xF800
        .word 4,6,7,0x001F, 4,7,5,0x001F
        .word 0,4,5,0xFFE0, 0,5,1,0xFFE0
        .word 2,3,7,0x07E0, 2,7,6,0x07E0
        .word 0,2,6,0x07FF, 0,6,4,0x07FF
        .word 1,5,7,0xF81F, 1,7,3,0xF81F
        .include "cube_sine_q14.inc"

        .data
cube_angle:
        .word 0
        .bss
        .align 4
cube_points:
        .space 64
cube_descriptors:
        .space 336

