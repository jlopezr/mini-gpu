; span_threshold.asm -- placa 38: umbral CPU/ROP para spans de MiniGL 3D.
; Cada muestra son ROWS spans RGB565/Z16: LT, Z Q8, SAT y escritura de Z+color.
; El ROP usa CONFIG + SPAN compacto, como el backend 3D previsto.  Los 64
; submits se dejan encolar y se espera solo al final: mide el coste extremo a
; extremo de un triángulo alto, incluida la presión de la FIFO.
;
; Resultados: done, errors y, por cada ancho de widths, CPU/ROP u32 en cycles.

.include "mmio.inc"

.equ COLOR,       0x00600000
.equ ZBUF,        0x00800000
.equ STRIDE,      656
.equ ROWS,        64
.equ Z_INITIAL,   100
.equ ROP_Z_INITIAL, 25600             ; Z_INITIAL << FRAC (FRAC = 8)
.equ ROP_DX,      256                 ; un U16 por pixel, en Q8
.equ COLOR_VALUE, 0x5A3C
.equ MODE,        0x2863              ; LT | WZ | WC | FRAC=8 | SAT
.equ CONFIG_ALL,  31                  ; bases, strides, color, Z y modo
.equ COMPACT,     0x1000
.equ WIDTH_COUNT, 15

start:
    JAL R31, bench_init
    LI R1, errors
    STORE R0, R1, 0
    LI R24, widths
    LI R25, results
    MOVI R26, WIDTH_COUNT

next_width:
    LOAD R22, R24, 0
    ADDI R24, R24, 4

    ; CPU: el mismo bucle de fragmentos que MiniGL para el caso interior,
    ; donde clamp no altera Z: if (z < *depth) { *depth=z; *color=fill; }.
    JAL R31, prep_span
    JAL R31, bench_now
    ADD R20, R1, R0
    LI R2, COLOR+2
    LI R3, ZBUF+2
    MOVI R4, ROWS
cpu_row:
    ADD R5, R2, R0
    ADD R6, R3, R0
    ADD R7, R22, R0
    MOVI R8, Z_INITIAL
cpu_pixel:
    LOADUH R9, R6, 0
    BGEU R8, R9, cpu_skip
    STOREH R8, R6, 0
    LI R10, COLOR_VALUE
    STOREH R10, R5, 0
cpu_skip:
    ADDI R8, R8, 1
    ADDI R5, R5, 2
    ADDI R6, R6, 2
    ADDI R7, R7, -1
    BNE R7, R0, cpu_pixel
    LI R7, STRIDE
    ADD R2, R2, R7
    ADD R3, R3, R7
    ADDI R4, R4, -1
    BNE R4, R0, cpu_row
    JAL R31, bench_now
    SUB R1, R1, R20
    STORE R1, R25, 0
    JAL R31, check_span

    ; ROP: CONFIG es parte de la medida; los spans compactos solo actualizan
    ; offsets y ancho. Z0, dX, color y el modo pertenecen al triángulo.
    JAL R31, prep_span
    JAL R31, bench_now                 ; confirma la inicializacion CPU de Z
    ADD R20, R1, R0
    LI R1, COLOR
    LI R2, ZBUF
    LI R3, STRIDE
    LI R4, COLOR_VALUE
    LI R5, ROP_Z_INITIAL
    LI R6, ROP_DX
    LI R7, MODE
    LI R8, CONFIG_ALL
    ROPSET P0, R1, P1, R2
    ROPSET P2, R3, P3, R3
    ROPSET P4, R4, P5, R5
    ROPSET P6, R6, P7, R0
    ROPSET P8, R7, PMODE, R8
    ROPSUBMIT CONFIG
    LI R9, COMPACT
    ROPSET PMODE, R9
    ROPSET P8, R0, P9, R0            ; reservados a cero en SPAN compacto
    MOVI R1, 2                         ; offsets sobre las bases configuradas
    MOVI R2, ROWS
    MOVI R3, 1
rop_row:
    ROPSET P0, R1, P1, R1
    ROPSET P2, R22, P3, R3
    ROPSUBMIT SPAN                     ; compacto, conserva los otros parametros
    LI R4, STRIDE
    ADD R1, R1, R4
    ADDI R2, R2, -1
    BNE R2, R0, rop_row
    ROPWAIT INV
    JAL R31, bench_now
    SUB R1, R1, R20
    STORE R1, R25, 4
    JAL R31, check_span

    ADDI R25, R25, 8
    ADDI R26, R26, -1
    BNE R26, R0, next_width
    LI R1, done
    MOVI R2, 1
    STORE R2, R1, 0
    HALT

; Inicializa todos los Z a 65535. COLOR no se lee antes de escribirse.
prep_span:
    LI R1, ZBUF
    LI R2, 10496                       ; ROWS * STRIDE / 4
    LI R3, 0xFFFFFFFF
prep_loop:
    STORE R3, R1, 0
    ADDI R1, R1, 4
    ADDI R2, R2, -1
    BNE R2, R0, prep_loop
    RET

; Comprueba extremos de la primera y ultima fila; la formula no depende del
; ancho salvo en el ultimo pixel.
check_span:
    LI R1, ZBUF+2
    LOADUH R2, R1, 0
    MOVI R3, Z_INITIAL
    BNE R2, R3, bad
    LI R1, COLOR+2
    LOADUH R2, R1, 0
    LI R3, COLOR_VALUE
    BNE R2, R3, bad
    RET

bad:
    LI R1, errors
    LOAD R2, R1, 0
    ADDI R2, R2, 1
    STORE R2, R1, 0
    RET

.include "bench.inc"

.data
done:    .word 0
errors:  .word 0
widths:  .word 1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 160, 240, 320
results: .word 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
         .word 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
