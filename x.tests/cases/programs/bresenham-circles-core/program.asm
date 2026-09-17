; Punto medio aislado del video. Cada radio ocupa 512 bytes: contador seguido
; de la secuencia exacta de puntos emitida por la simetria de ocho.

    MOVHI R28, 0x0010
    MOVI R9, 32
    MOVI R10, 32

    ADDI R26, R28, 4
    MOVI R27, 0
    MOVI R14, 0
    JAL R31, circle
    STORE R27, R28, 0

    ADDI R26, R28, 516
    MOVI R27, 0
    MOVI R14, 1
    JAL R31, circle
    STORE R27, R28, 512

    ADDI R26, R28, 1028
    MOVI R27, 0
    MOVI R14, 2
    JAL R31, circle
    STORE R27, R28, 1024

    ADDI R26, R28, 1540
    MOVI R27, 0
    MOVI R14, 3
    JAL R31, circle
    STORE R27, R28, 1536

    ADDI R26, R28, 2052
    MOVI R27, 0
    MOVI R14, 4
    JAL R31, circle
    STORE R27, R28, 2048

    ADDI R26, R28, 2564
    MOVI R27, 0
    MOVI R14, 7
    JAL R31, circle
    STORE R27, R28, 2560

    ADDI R26, R28, 3076
    MOVI R27, 0
    MOVI R14, 18
    JAL R31, circle
    STORE R27, R28, 3072
    HALT

circle:
    ADDI R11, R14, 0
    MOVI R12, 0
    MOVI R13, 0
circle_step:
    BLT R11, R12, circle_done
    JAL R29, plot8
    ADDI R12, R12, 1
    ADD R17, R12, R12
    ADDI R17, R17, 1
    ADD R13, R13, R17
    SUB R17, R13, R11
    ADD R17, R17, R17
    ADDI R17, R17, 1
    BGE R0, R17, circle_step
    ADDI R11, R11, -1
    ADD R17, R11, R11
    SUB R17, R0, R17
    ADDI R17, R17, 1
    ADD R13, R13, R17
    BRA circle_step
circle_done:
    JR R31

plot8:
    ADD R4, R9, R11
    ADD R5, R10, R12
    JAL R30, record_pixel
    SUB R4, R9, R11
    JAL R30, record_pixel
    SUB R5, R10, R12
    JAL R30, record_pixel
    ADD R4, R9, R11
    JAL R30, record_pixel
    ADD R4, R9, R12
    ADD R5, R10, R11
    JAL R30, record_pixel
    SUB R4, R9, R12
    JAL R30, record_pixel
    SUB R5, R10, R11
    JAL R30, record_pixel
    ADD R4, R9, R12
    JAL R30, record_pixel
    JR R29

record_pixel:
    SHLI R7, R5, 16
    OR R7, R7, R4
    STORE R7, R26, 0
    ADDI R26, R26, 4
    ADDI R27, R27, 1
    JR R30
