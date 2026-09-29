; Scroll continuo de la consola 80x30 del prototipo 30.
; No hay scroll por hardware: cada vuelta la CPU copia las filas 1..29 sobre
; las 0..28 (LOAD + STORE de cada celda) y escribe una fila nueva abajo. La
; pantalla arranca vacia, asi que se llena desde abajo y luego sigue subiendo.
;
; El texto es el flujo ASCII imprimible 32..126 repetido, con el color
; cambiando por linea (paleta 1, 2, 3).

start:
    LI    R20, 0x80200000       ; VIDEO_BASE

    ; PALETTE[1] naranja CPC, [2] cian, [3] blanco.
    LI    R1, 0x00f0c040
    STORE R1, R20, 0x1004
    LI    R1, 0x0040e0f0
    STORE R1, R20, 0x1008
    LI    R1, 0x00ffffff
    STORE R1, R20, 0x100c

    ; CONFIG.TEXT_ENABLE en shadow y commit en la siguiente entrada a VBlank.
    MOVI  R1, 4
    STORE R1, R20, 0x0040
    MOVI  R1, 2
    STORE R1, R20, 0x000c
wait_commit:
    LOAD  R2, R20, 0x000c
    BNE   R2, R0, wait_commit

    ADDI  R21, R20, 0x6000      ; TEXT[0]
    ADDI  R10, R0, 32           ; siguiente caracter del flujo
    ADDI  R11, R0, 0x100        ; atributo de la linea: FG=1
    ADDI  R8, R0, 127           ; limite del flujo (exclusivo)
    ADDI  R12, R0, 0x400        ; FG pasa de 3 a 1 al llegar aqui
    LI    R13, 60000            ; retardo entre lineas

scroll:
    ; Copiar filas 1..29 a 0..28: 29 * 80 celdas = 9280 bytes.
    ADDI  R3, R21, 0            ; destino
    ADDI  R4, R21, 320          ; origen
    ADDI  R5, R21, 9280         ; fin del destino = inicio de la fila 29
copy:
    LOAD  R1, R4, 0
    STORE R1, R3, 0
    ADDI  R3, R3, 4
    ADDI  R4, R4, 4
    BLT   R3, R5, copy

    ; Fila 29 nueva (R3 ya apunta a ella).
    ADDI  R6, R3, 320
newrow:
    OR    R1, R10, R11
    STORE R1, R3, 0
    ADDI  R3, R3, 4
    ADDI  R10, R10, 1
    BLT   R10, R8, same_char
    ADDI  R10, R0, 32
same_char:
    BLT   R3, R6, newrow

    ADDI  R11, R11, 0x100
    BLT   R11, R12, delay_start
    ADDI  R11, R0, 0x100

delay_start:
    ADDI  R14, R0, 0
delay:
    ADDI  R14, R14, 1
    BLT   R14, R13, delay

    BEQ   R0, R0, scroll
