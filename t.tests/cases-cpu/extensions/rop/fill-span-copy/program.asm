; ============================================================
; fill-span-copy.asm - la familia ROP (0x37, 1.isa/isa.md §7.5) en la CPU
;
; Tres trabajos encolados sin esperar entre ellos; la semantica es secuencial,
; asi que el SPAN ve la Z que dejo el FILL de antes.
;   1. FILL de 2 filas de 32 bytes en 0x00110000 (stride 64) con un patron.
;   2. FILL del Z-buffer (8 pixeles Z16 en 0x00121000) a 0xFFFF y del de
;      color (0x00120000) a 0.
;   3. SPAN explicito de 8 pixeles: Z16 con FRAC = 8 y SAT, LT, escribe Z y
;      color. Z(x) = sat16((-256 + x * 0x00400000) >> 8): 0, 16383, 32767,
;      49151 pasan; 65535 y los saturados no (no son menores que 0xFFFF).
;   4. COPY de la primera fila del FILL a 0x00130000.
; ROPWAIT INV y la CPU lee los resultados: estas lineas no estaban en la
; D-cache, pero INV lo garantiza igualmente.
;
; Registros al parar:
;   R10 suma del FILL (16 palabras)   R11 suma de la Z (4 palabras)
;   R12 suma del color (4 palabras)   R13 suma del COPY (8 palabras)
;   R14 ROPSTATUS al final (nada pendiente, 16 huecos: 0x1000)
; ============================================================

start:
    ; 1. FILL
    LI    R1, 0x00110000
    MOVI  R2, 32
    ROPSET P0, R1, P1, R2          ; destino, ancho en bytes
    MOVI  R3, 2
    MOVI  R4, 64
    ROPSET P2, R3, P3, R4          ; filas, stride
    LI    R5, 0xC0DE5A17
    ROPSET P4, R5, PMODE, R0
    ROPSUBMIT FILL

    ; 2. Z a 0xFFFF y color a 0, 16 bytes cada uno
    LI    R6, 0x00121000
    MOVI  R2, 16
    MOVI  R3, 1
    ROPSET P1, R2, P2, R3
    MOVI  R7, -1
    ROPSUBMIT FILL, P0, R6, P4, R7
    LI    R8, 0x00120000
    ROPSUBMIT FILL, P0, R8, P4, R0

    ; 3. SPAN: P0 color, P1 Z, P2 ancho 8, P3 filas 1, P4/P5 strides,
    ;    P6 color, P7 z0, P8 dx, P9 dy
    ROPSET P0, R8, P1, R6
    MOVI  R2, 8
    ROPSET P2, R2, P3, R3
    ROPSET P4, R4, P5, R4
    LI    R9, 0xABCD
    MOVI  R15, -256
    ROPSET P6, R9, P7, R15
    LI    R16, 0x00400000
    ROPSET P8, R16, P9, R0
    LI    R17, 0x2863              ; SAT, FRAC 8, escribe color y Z, LT
    ROPSUBMIT SPAN, PMODE, R17

    ; 4. COPY de 32 bytes de 0x00110000 a 0x00130000
    LI    R18, 0x00130000
    MOVI  R2, 32
    ROPSET P0, R1, P1, R18         ; origen, destino
    ROPSET P2, R2, P3, R3          ; ancho, filas
    ROPSET P4, R4, P5, R4          ; strides
    ROPSET PMODE, R0
    ROPSUBMIT COPY

    ROPWAIT INV

    ; Sumas
    MOVI  R10, 0
    ADD   R19, R1, R0
    MOVI  R20, 2
fill_row:
    MOVI  R21, 8
    ADD   R22, R19, R0
fill_word:
    LOAD  R23, R22, 0
    ADD   R10, R10, R23
    ADDI  R22, R22, 4
    ADDI  R21, R21, -1
    BNE   R21, R0, fill_word
    ADDI  R19, R19, 64
    ADDI  R20, R20, -1
    BNE   R20, R0, fill_row

    LOAD  R11, R6, 0
    LOAD  R23, R6, 4
    ADD   R11, R11, R23
    LOAD  R23, R6, 8
    ADD   R11, R11, R23
    LOAD  R23, R6, 12
    ADD   R11, R11, R23

    LOAD  R12, R8, 0
    LOAD  R23, R8, 4
    ADD   R12, R12, R23
    LOAD  R23, R8, 8
    ADD   R12, R12, R23
    LOAD  R23, R8, 12
    ADD   R12, R12, R23

    MOVI  R13, 0
    MOVI  R21, 8
    ADD   R22, R18, R0
copy_word:
    LOAD  R23, R22, 0
    ADD   R13, R13, R23
    ADDI  R22, R22, 4
    ADDI  R21, R21, -1
    BNE   R21, R0, copy_word

    ROPSTATUS R14
    HALT
