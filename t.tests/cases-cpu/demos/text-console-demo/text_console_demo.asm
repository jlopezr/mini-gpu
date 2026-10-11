; Demo de consola 80x30 del prototipo 30.
; Muestra texto sobre el patron de video, sin usar SDRAM.

start:
    LI    R20, 0x80200000       ; VIDEO_BASE

    ; PALETTE[1] naranja CPC, [2] cian, [15] blanco.
    LI    R1, 0x00f0c040
    STORE R1, R20, 0x1004
    LI    R1, 0x0040e0f0
    STORE R1, R20, 0x1008
    LI    R1, 0x00ffffff
    STORE R1, R20, 0x103c

    ; Fila 12, columna 30: "MINIGPU 2D". FG=1, BG=0.
    ; TEXT + 4 * (12*80 + 30) = 0x6f78.
    LI R1, 0x0000014d
    STORE R1, R20, 0x6f78
    LI R1, 0x00000149
    STORE R1, R20, 0x6f7c
    LI R1, 0x0000014e
    STORE R1, R20, 0x6f80
    LI R1, 0x00000149
    STORE R1, R20, 0x6f84
    LI R1, 0x00000147
    STORE R1, R20, 0x6f88
    LI R1, 0x00000150
    STORE R1, R20, 0x6f8c
    LI R1, 0x00000155
    STORE R1, R20, 0x6f90
    LI R1, 0x00000120
    STORE R1, R20, 0x6f94
    LI R1, 0x00000132
    STORE R1, R20, 0x6f98
    LI R1, 0x00000144
    STORE R1, R20, 0x6f9c

    ; Fila 14, columna 28: "CPC464 FONT". FG=2, BG=0.
    ; TEXT + 4 * (14*80 + 28) = 0x71f0.
    LI R1, 0x00000243
    STORE R1, R20, 0x71f0
    LI R1, 0x00000250
    STORE R1, R20, 0x71f4
    LI R1, 0x00000243
    STORE R1, R20, 0x71f8
    LI R1, 0x00000234
    STORE R1, R20, 0x71fc
    LI R1, 0x00000236
    STORE R1, R20, 0x7200
    LI R1, 0x00000234
    STORE R1, R20, 0x7204
    LI R1, 0x00000220
    STORE R1, R20, 0x7208
    LI R1, 0x00000246
    STORE R1, R20, 0x720c
    LI R1, 0x0000024f
    STORE R1, R20, 0x7210
    LI R1, 0x0000024e
    STORE R1, R20, 0x7214
    LI R1, 0x00000254
    STORE R1, R20, 0x7218

    ; Tabla con los 256 codigos de la ROM (0..255), 32 columnas x 8 filas,
    ; FG=15 BG=0, desde la fila 17, columna 24.
    ; TEXT + 4 * (17*80 + 24) = 0x75a0.
    ADDI  R3, R20, 0x75a0       ; puntero a la celda
    MOVI  R4, 0                 ; codigo de caracter
    ADDI  R5, R0, 256
    MOVI  R6, 0                 ; columna actual
    MOVI  R7, 32
table_loop:
    ORI   R1, R4, 0x0f00
    STORE R1, R3, 0
    ADDI  R3, R3, 4
    ADDI  R4, R4, 1
    ADDI  R6, R6, 1
    BLT   R6, R7, table_same_row
    MOVI  R6, 0
    ADDI  R3, R3, 192           ; saltar a la fila siguiente: (80-32)*4
table_same_row:
    BLT   R4, R5, table_loop

    ; CONFIG.TEXT_ENABLE en shadow y commit en la siguiente entrada a VBlank.
    MOVI  R1, 4
    STORE R1, R20, 0x0040
    MOVI  R1, 2
    STORE R1, R20, 0x000c

wait_commit:
    LOAD  R2, R20, 0x000c
    BNE   R2, R0, wait_commit
    HALT
