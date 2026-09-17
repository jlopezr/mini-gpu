; Bresenham de rectas aislado del video. Cada caso deja primero el numero de
; puntos y despues la secuencia (y << 16) | x en una ranura de 128 bytes.

    MOVHI R28, 0x0010

    ; punto unico
    ADDI R26, R28, 4
    MOVI R27, 0
    MOVI R9, 5
    MOVI R10, 5
    MOVI R11, 5
    MOVI R12, 5
    JAL R31, drawline
    STORE R27, R28, 0

    ; horizontal en los dos sentidos
    ADDI R26, R28, 132
    MOVI R27, 0
    MOVI R9, 1
    MOVI R10, 4
    MOVI R11, 13
    MOVI R12, 4
    JAL R31, drawline
    STORE R27, R28, 128

    ADDI R26, R28, 260
    MOVI R27, 0
    MOVI R9, 13
    MOVI R10, 4
    MOVI R11, 1
    MOVI R12, 4
    JAL R31, drawline
    STORE R27, R28, 256

    ; vertical en los dos sentidos
    ADDI R26, R28, 388
    MOVI R27, 0
    MOVI R9, 7
    MOVI R10, 1
    MOVI R11, 7
    MOVI R12, 13
    JAL R31, drawline
    STORE R27, R28, 384

    ADDI R26, R28, 516
    MOVI R27, 0
    MOVI R9, 7
    MOVI R10, 13
    MOVI R11, 7
    MOVI R12, 1
    JAL R31, drawline
    STORE R27, R28, 512

    ; un representante de cada octante, todos desde (8,8)
    ADDI R26, R28, 644
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 14
    MOVI R12, 10
    JAL R31, drawline
    STORE R27, R28, 640

    ADDI R26, R28, 772
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 10
    MOVI R12, 14
    JAL R31, drawline
    STORE R27, R28, 768

    ADDI R26, R28, 900
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 6
    MOVI R12, 14
    JAL R31, drawline
    STORE R27, R28, 896

    ADDI R26, R28, 1028
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 2
    MOVI R12, 10
    JAL R31, drawline
    STORE R27, R28, 1024

    ADDI R26, R28, 1156
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 2
    MOVI R12, 6
    JAL R31, drawline
    STORE R27, R28, 1152

    ADDI R26, R28, 1284
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 6
    MOVI R12, 2
    JAL R31, drawline
    STORE R27, R28, 1280

    ADDI R26, R28, 1412
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 10
    MOVI R12, 2
    JAL R31, drawline
    STORE R27, R28, 1408

    ADDI R26, R28, 1540
    MOVI R27, 0
    MOVI R9, 8
    MOVI R10, 8
    MOVI R11, 14
    MOVI R12, 6
    JAL R31, drawline
    STORE R27, R28, 1536
    HALT

drawline:
    SUB R13, R11, R9
    MOVI R15, 1
    BGE R13, R0, dx_ready
    SUB R13, R0, R13
    MOVI R15, -1
dx_ready:
    SUB R14, R12, R10
    MOVI R16, 1
    BGE R14, R0, dy_positive
    MOVI R16, -1
    BRA dy_ready
dy_positive:
    SUB R14, R0, R14
dy_ready:
    ADD R17, R13, R14
line_step:
    ADDI R4, R9, 0
    ADDI R5, R10, 0
    JAL R30, record_pixel
    BNE R9, R11, advance
    BEQ R10, R12, line_done
advance:
    ADD R18, R17, R17
    BLT R18, R14, skip_x
    ADD R17, R17, R14
    ADD R9, R9, R15
skip_x:
    BLT R13, R18, skip_y
    ADD R17, R17, R13
    ADD R10, R10, R16
skip_y:
    BRA line_step
line_done:
    JR R31

record_pixel:
    SHLI R7, R5, 16
    OR R7, R7, R4
    STORE R7, R26, 0
    ADDI R26, R26, 4
    ADDI R27, R27, 1
    JR R30
