; filepath: c:\Users\j_lop\Documents\repos\mini-gpu\x.tests\cases\video\fire\fire.asm
; fire.asm - referencia secuencial del efecto de fuego

.include "mmio.inc"

.equ WIDTH,       64
.equ HEIGHT,      120
.equ DECAY,       2
.equ PITCH,       640
.equ FB0,         0x01000000
.equ FB1,         0x01040000

.text

start:
    LI    R28, MMIO_VIDEO_BASE
    LI    R29, stack_top
    LI    R20, heat_a
    LI    R21, heat_b

    LI    R1, FB0
    STORE R1, R28, MMIO_VIDEO_FB_FRONT_OFF
    LI    R1, FB1
    STORE R1, R28, MMIO_VIDEO_FB_BACK_OFF

    LI    R1, seed_rng
    LI    R2, 0x2545F491
    STORE R2, R1, 0

    MOVI  R1, MMIO_VIDEO_MODE_SCANOUT
    STORE R1, R28, MMIO_VIDEO_CTRL_OFF

frame:
    JAL   R31, generate_source
    JAL   R31, propagate

    ; Intercambiar los mapas de calor.
    ADDI  R1, R20, 0
    ADDI  R20, R21, 0
    ADDI  R21, R1, 0

    LOAD  R27, R28, MMIO_VIDEO_FB_BACK_OFF
    JAL   R31, render

    MOVI  R1, 1
    STORE R1, R28, MMIO_VIDEO_SWAP_OFF

wait_swap:
    LOAD  R1, R28, MMIO_VIDEO_SWAP_OFF
    BNE   R1, R0, wait_swap
    BRA   frame


; =========================================================================
; generate_source - genera la fila inferior de R20
; =========================================================================

generate_source:
    ADDI  R29, R29, -4
    STORE R31, R29, 0

    ADDI  R5, R20, 7616      ; fila inferior de heat_a/heat_b
    MOVI  R6, 0              ; x

@source_loop:
    JAL   R31, rng_next
    ANDI  R1, R1, 0xFF

    MOVI  R4, 80
    BLT   R4, R1, @source_hot
    MOVI  R1, 0

@source_hot:
    STOREB R1, R5, 0
    ADDI  R5, R5, 1
    ADDI  R6, R6, 1
    MOVI  R4, WIDTH
    BLT   R6, R4, @source_loop

    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET


; =========================================================================
; propagate - calcula HEIGHT-1 filas en R21 y copia la fuente
; =========================================================================

propagate:
    MOVI  R10, 0               ; y

@prop_row:
    ADDI  R11, R10, 1
    SHLI  R11, R11, 6          ; (y+1)*64
    ADD   R11, R11, R20        ; fuente

    SHLI  R12, R10, 6          ; y*64
    ADD   R12, R12, R21        ; destino

    MOVI  R13, 0               ; x

@prop_pixel:
    ; izquierda, con clamp en x=0
    BEQ   R13, R0, @left_edge
    ADDI  R14, R11, -1
    ADD   R14, R14, R13
    LOADUB R1, R14, 0
    BRA   @left_done

@left_edge:
    ADD   R14, R11, R13
    LOADUB R1, R14, 0

@left_done:
    ADD   R14, R11, R13
    LOADUB R2, R14, 0           ; centro

    MOVI  R15, WIDTH-1
    BEQ   R13, R15, @right_edge
    ADDI  R14, R13, 1
    ADD   R14, R11, R14
    LOADUB R3, R14, 0
    BRA   @right_done

@right_edge:
    ADD   R14, R11, R13
    LOADUB R3, R14, 0

@right_done:
    ADD   R4, R1, R2
    ADD   R4, R4, R2
    ADD   R4, R4, R3
    SHRI  R4, R4, 2
    ADDI  R4, R4, -2 ; -DECAY

    BGE   R4, R0, @heat_positive
    MOVI  R4, 0

@heat_positive:
    ADD   R14, R12, R13
    STOREB R4, R14, 0

    ADDI  R13, R13, 1
    MOVI  R15, WIDTH
    BLT   R13, R15, @prop_pixel

    ADDI  R10, R10, 1
    MOVI  R15, HEIGHT-1
    BLT   R10, R15, @prop_row

    ; Copiar la fila fuente al mapa destino.
    LI    R10, 7616 ; (HEIGHT-1)*WIDTH
    ADD   R11, R20, R10
    ADD   R12, R21, R10
    MOVI  R13, 0

@copy_bottom:
    LOADUB R1, R11, 0
    STOREB R1, R12, 0
    ADDI  R11, R11, 1
    ADDI  R12, R12, 1
    ADDI  R13, R13, 1
    MOVI  R15, WIDTH
    BLT   R13, R15, @copy_bottom
    RET


; =========================================================================
; render - convierte el mapa de calor en RGB565
;
; Cada celda ocupa 5x2 píxeles:
;   64 * 5 = 320
;   120 * 2 = 240
; =========================================================================

render:
    MOVI  R10, 0               ; y
    ADDI  R11, R20, 0          ; mapa actual

@render_row:
    SHLI  R12, R10, 6
    ADD   R12, R12, R11        ; fila del mapa

    ; framebuffer_y = y * 2 * 640 = y * 1024 + y * 256
    SHLI  R13, R10, 10
    SHLI  R2, R10, 8
    ADD   R13, R13, R2

    ADD   R14, R27, R13        ; fila superior
    ADDI  R15, R14, PITCH      ; fila inferior

    MOVI  R1, 0                ; x

@render_pixel:
    ADD   R2, R12, R1
    LOADUB R3, R2, 0            ; heat

    ; Paleta de fuego RGB565 por tramos:
    ;   0..63    negro -> rojo
    ;   64..191  rojo  -> amarillo
    ;   192..255 amarillo -> blanco
    MOVI  R5, 64
    BLT   R3, R5, @palette_red

    MOVI  R4, 31
    SHLI  R4, R4, 11            ; rojo al máximo
    MOVI  R5, 192
    BLT   R3, R5, @palette_orange

    MOVI  R5, 63
    SHLI  R5, R5, 5
    OR    R4, R4, R5            ; amarillo
    ADDI  R5, R3, -192
    SHRI  R5, R5, 1             ; azul 0..31
    OR    R4, R4, R5
    BRA   @palette_done

@palette_orange:
    ADDI  R5, R3, -64
    SHRI  R5, R5, 1             ; verde 0..63
    SHLI  R5, R5, 5
    OR    R4, R4, R5
    BRA   @palette_done

@palette_red:
    SHRI  R4, R3, 1             ; rojo 0..31
    SHLI  R4, R4, 11

@palette_done:

    SHLI  R2, R1, 1
    SHLI  R5, R1, 3
    ADD   R2, R2, R5            ; x * 10

    ADD   R5, R14, R2
    STOREH R4, R5, 0
    STOREH R4, R5, 2
    STOREH R4, R5, 4
    STOREH R4, R5, 6
    STOREH R4, R5, 8

    ADD   R5, R15, R2
    STOREH R4, R5, 0
    STOREH R4, R5, 2
    STOREH R4, R5, 4
    STOREH R4, R5, 6
    STOREH R4, R5, 8

    ADDI  R1, R1, 1
    MOVI  R2, WIDTH
    BLT   R1, R2, @render_pixel

    ADDI  R10, R10, 1
    MOVI  R2, HEIGHT
    BLT   R10, R2, @render_row
    RET


; =========================================================================
; rng_next - xorshift32
; =========================================================================

rng_next:
    LI    R2, seed_rng
    LOAD  R1, R2, 0

    SHLI  R3, R1, 13
    XOR   R1, R1, R3

    SHRI  R3, R1, 17
    XOR   R1, R1, R3

    SHLI  R3, R1, 5
    XOR   R1, R1, R3

    STORE R1, R2, 0
    RET


.rodata


.bss

heat_a:    .space 7680; WIDTH*HEIGHT
heat_b:    .space 7680; WIDTH*HEIGHT
seed_rng:  .space 4

           .space 512
stack_top:
