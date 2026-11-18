; ============================================================
; fill-copy.asm - el motor de DMA de la 38 (mmio.md §11.1, EXPERIMENTAL)
;
; 1. Identidad: DMA_ID = "DMA1", DMA_CAPS = numero de canales.
; 2. Canal 0, FILL 2D: 4 filas de 64 bytes con PATTERN, stride 128.
; 3. Canal 1, COPY 2D: la CPU escribe 32 palabras (0..31) en el origen y el
;    DMA copia 4 filas de 32 bytes (stride origen 32, destino 64). Las
;    escrituras de la CPU pueden seguir en el bufer de combinacion al dar
;    START: el motor no emite lecturas mientras `wb_dirty` este alto.
; 4. La CPU lee los dos destinos y calcula dos sumas: la simple y la
;    ponderada por posicion (detecta palabras cambiadas de sitio).
;
; Los destinos no se han tocado antes con la CPU, asi que la D-cache no tiene
; copias viejas: la regla de coherencia de §11.1 se respeta.
;
; Registros al parar:
;   R1  DMA_ID              R2  DMA_CAPS
;   R3  STATUS canal 0      R4  BYTES_DONE canal 0
;   R5  STATUS canal 1      R6  BYTES_DONE canal 1
;   R10 suma del FILL       R11 suma ponderada del FILL
;   R12 suma del COPY       R13 suma ponderada del COPY
; ============================================================

.include "mmio.inc"

; Offsets del bloque DMA. No estan en mmio_map.vh porque la interfaz aun no
; esta congelada (mmio.md §11.1).
.equ DMA_SRC,        0x00
.equ DMA_DST,        0x04
.equ DMA_WIDTH,      0x08
.equ DMA_HEIGHT,     0x0C
.equ DMA_SRC_STRIDE, 0x10
.equ DMA_DST_STRIDE, 0x14
.equ DMA_PATTERN,    0x18
.equ DMA_CTRL,       0x1C
.equ DMA_STATUS,     0x20
.equ DMA_BYTES_DONE, 0x24
.equ DMA_CH1,        0x40
.equ DMA_ID,         0x200
.equ DMA_CAPS,       0x204

start:
    LI    R20, MMIO_DMA_BASE
    LOAD  R1, R20, DMA_ID
    LOAD  R2, R20, DMA_CAPS

    ; --- Canal 0: FILL de 4 x 64 bytes en 0x00110000, stride 128 ---
    MOVHI R21, 0x0011                 ; destino del FILL
    STORE R21, R20, DMA_DST
    MOVI  R7, 64
    STORE R7, R20, DMA_WIDTH
    MOVI  R7, 4
    STORE R7, R20, DMA_HEIGHT
    MOVI  R7, 128
    STORE R7, R20, DMA_DST_STRIDE
    LI    R7, 0xC0DE5A17
    STORE R7, R20, DMA_PATTERN
    MOVI  R7, 3                       ; START | FILL
    STORE R7, R20, DMA_CTRL

    ; --- Origen del COPY: 32 palabras 0..31 en 0x00100000 ---
    MOVHI R22, 0x0010
    MOVI  R7, 0
    MOVI  R8, 32
    ADD   R9, R22, R0
src_loop:
    STORE R7, R9, 0
    ADDI  R9, R9, 4
    ADDI  R7, R7, 1
    BNE   R7, R8, src_loop

    ; --- Canal 1: COPY de 4 x 32 bytes a 0x00120000, strides 32 / 64 ---
    MOVHI R23, 0x0012
    STORE R22, R20, DMA_CH1+DMA_SRC
    STORE R23, R20, DMA_CH1+DMA_DST
    MOVI  R7, 32
    STORE R7, R20, DMA_CH1+DMA_WIDTH
    STORE R7, R20, DMA_CH1+DMA_SRC_STRIDE
    MOVI  R7, 4
    STORE R7, R20, DMA_CH1+DMA_HEIGHT
    MOVI  R7, 64
    STORE R7, R20, DMA_CH1+DMA_DST_STRIDE
    MOVI  R7, 1                       ; START (COPY)
    STORE R7, R20, DMA_CH1+DMA_CTRL

    ; --- Esperar a los dos: DONE (bit 1) o ERROR (bit 2) ---
wait0:
    LOAD  R3, R20, DMA_STATUS
    ANDI  R7, R3, 6
    BEQ   R7, R0, wait0
wait1:
    LOAD  R5, R20, DMA_CH1+DMA_STATUS
    ANDI  R7, R5, 6
    BEQ   R7, R0, wait1
    LOAD  R4, R20, DMA_BYTES_DONE
    LOAD  R6, R20, DMA_CH1+DMA_BYTES_DONE

    ; --- Sumas del FILL: 4 filas x 16 palabras ---
    MOVI  R10, 0
    MOVI  R11, 0
    MOVI  R14, 1                      ; peso
    ADD   R9, R21, R0                 ; inicio de fila
    MOVI  R15, 4
fill_row:
    ADD   R16, R9, R0
    MOVI  R17, 16
fill_word:
    LOAD  R7, R16, 0
    ADD   R10, R10, R7
    MUL   R8, R7, R14
    ADD   R11, R11, R8
    ADDI  R14, R14, 1
    ADDI  R16, R16, 4
    ADDI  R17, R17, -1
    BNE   R17, R0, fill_word
    ADDI  R9, R9, 128
    ADDI  R15, R15, -1
    BNE   R15, R0, fill_row

    ; --- Sumas del COPY: 4 filas x 8 palabras ---
    MOVI  R12, 0
    MOVI  R13, 0
    MOVI  R14, 1
    ADD   R9, R23, R0
    MOVI  R15, 4
copy_row:
    ADD   R16, R9, R0
    MOVI  R17, 8
copy_word:
    LOAD  R7, R16, 0
    ADD   R12, R12, R7
    MUL   R8, R7, R14
    ADD   R13, R13, R8
    ADDI  R14, R14, 1
    ADDI  R16, R16, 4
    ADDI  R17, R17, -1
    BNE   R17, R0, copy_word
    ADDI  R9, R9, 64
    ADDI  R15, R15, -1
    BNE   R15, R0, copy_row

    HALT
