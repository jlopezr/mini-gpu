; bench_rop.asm -- placa 38: CPU contra ROP, ciclos de pared.
; Resultados: bench_done, bench_errors y seis u32 desde bench_results.
; El simulador funcional valida los resultados pero no mide ciclos; en placa,
; bench_now lee el contador PERF. Preparacion y comprobacion quedan fuera.

.include "mmio.inc"

.equ SRC,       0x00200000
.equ DST,       0x00400000
.equ COLOR,     0x00600000
.equ ZBUF,      0x00800000
.equ BYTES,     65536
.equ WORDS,     16384
.equ WIDTH,     320
.equ HEIGHT,    100
.equ STRIDE,    640
.equ PATTERN,   0xC0DE5A17
.equ COLORVAL,  0x5A3C

start:
    JAL R31, bench_init
    LI R4, bench_errors
    STORE R0, R4, 0

    ; ---- FILL: CPU --------------------------------------------------------
    JAL R31, prep_dst
    JAL R31, bench_now
    ADD R20, R1, R0
    LI R1, DST
    LI R2, WORDS
    LI R3, PATTERN
fill_cpu_loop:
    STORE R3, R1, 0
    ADDI R1, R1, 4
    ADDI R2, R2, -1
    BNE R2, R0, fill_cpu_loop
    JAL R31, bench_now
    SUB R1, R1, R20
    LI R2, bench_results
    STORE R1, R2, 0
    JAL R31, check_fill

    ; ---- FILL: ROP --------------------------------------------------------
    JAL R31, prep_dst
    JAL R31, bench_now
    ADD R20, R1, R0
    LI R1, DST
    LI R2, BYTES
    MOVI R3, 1
    LI R4, BYTES
    LI R5, PATTERN
    ROPSET P0, R1, P1, R2
    ROPSET P2, R3, P3, R4
    ROPSET P4, R5, PMODE, R0
    ROPSUBMIT FILL
    ROPWAIT INV
    JAL R31, bench_now
    SUB R1, R1, R20
    LI R2, bench_results
    STORE R1, R2, 4
    JAL R31, check_fill

    ; ---- COPY: CPU --------------------------------------------------------
    JAL R31, prep_src
    JAL R31, prep_dst
    JAL R31, bench_now
    ADD R20, R1, R0
    LI R1, SRC
    LI R2, DST
    LI R3, WORDS
copy_cpu_loop:
    LOAD R4, R1, 0
    STORE R4, R2, 0
    ADDI R1, R1, 4
    ADDI R2, R2, 4
    ADDI R3, R3, -1
    BNE R3, R0, copy_cpu_loop
    JAL R31, bench_now
    SUB R1, R1, R20
    LI R2, bench_results
    STORE R1, R2, 8
    JAL R31, check_copy

    ; ---- COPY: ROP --------------------------------------------------------
    JAL R31, prep_src
    JAL R31, prep_dst
    JAL R31, bench_now                 ; drena los STORE del origen
    ADD R20, R1, R0
    LI R1, SRC
    LI R2, DST
    LI R3, BYTES
    MOVI R4, 1
    LI R5, BYTES
    ROPSET P0, R1, P1, R2
    ROPSET P2, R3, P3, R4
    ROPSET P4, R5, P5, R5
    ROPSET PMODE, R0
    ROPSUBMIT COPY
    ROPWAIT INV
    JAL R31, bench_now
    SUB R1, R1, R20
    LI R2, bench_results
    STORE R1, R2, 12
    JAL R31, check_copy

    ; ---- SPAN LT Z16/C16: CPU --------------------------------------------
    JAL R31, prep_span
    JAL R31, bench_now
    ADD R20, R1, R0
    LI R1, COLOR
    LI R2, ZBUF
    MOVI R3, HEIGHT
    MOVI R4, 100
    LI R15, COLORVAL
span_cpu_row:
    MOVI R5, WIDTH
    ADD R6, R1, R0
    ADD R7, R2, R0
span_cpu_pixel:
    LOADUH R8, R7, 0
    BGEU R4, R8, span_cpu_skip
    STOREH R4, R7, 0
    STOREH R15, R6, 0
span_cpu_skip:
    ADDI R4, R4, 1
    ADDI R6, R6, 2
    ADDI R7, R7, 2
    ADDI R5, R5, -1
    BNE R5, R0, span_cpu_pixel
    LI R5, STRIDE
    ADD R1, R1, R5
    ADD R2, R2, R5
    ADDI R3, R3, -1
    BNE R3, R0, span_cpu_row
    JAL R31, bench_now
    SUB R1, R1, R20
    LI R2, bench_results
    STORE R1, R2, 16
    JAL R31, check_span

    ; ---- SPAN LT Z16/C16: ROP --------------------------------------------
    JAL R31, prep_span
    JAL R31, bench_now                 ; drena el Z inicializado por CPU
    ADD R20, R1, R0
    LI R1, COLOR
    LI R2, ZBUF
    MOVI R3, WIDTH
    MOVI R4, HEIGHT
    LI R5, STRIDE
    LI R6, COLORVAL
    MOVI R7, 100
    MOVI R8, 1
    MOVI R9, WIDTH
    MOVI R10, 0x63                      ; LT, escribe Z y color, ambos 16 bit
    ROPSET P0, R1, P1, R2
    ROPSET P2, R3, P3, R4
    ROPSET P4, R5, P5, R5
    ROPSET P6, R6, P7, R7
    ROPSET P8, R8, P9, R9
    ROPSET PMODE, R10
    ROPSUBMIT SPAN
    ROPWAIT INV
    JAL R31, bench_now
    SUB R1, R1, R20
    LI R2, bench_results
    STORE R1, R2, 20
    JAL R31, check_span

    LI R4, bench_done
    MOVI R5, 1
    STORE R5, R4, 0
    HALT

; Inicializaciones fuera de la ventana medida.
prep_dst:
    LI R1, DST
    LI R2, WORDS
prep_dst_loop:
    STORE R0, R1, 0
    ADDI R1, R1, 4
    ADDI R2, R2, -1
    BNE R2, R0, prep_dst_loop
    RET

prep_src:
    LI R1, SRC
    LI R2, WORDS
    LI R3, PATTERN
prep_src_loop:
    STORE R3, R1, 0
    ADDI R1, R1, 4
    ADDI R2, R2, -1
    BNE R2, R0, prep_src_loop
    RET

prep_span:
    LI R1, ZBUF
    LI R2, 16000                         ; 320 * 100 / dos Z16 por palabra
    LI R3, 0xFFFFFFFF
prep_span_loop:
    STORE R3, R1, 0
    ADDI R1, R1, 4
    ADDI R2, R2, -1
    BNE R2, R0, prep_span_loop
    RET

check_fill:
    LI R1, DST
    LOAD R2, R1, 0
    LI R3, PATTERN
    BNE R2, R3, bench_bad
    LI R1, DST+BYTES-4
    LOAD R2, R1, 0
    BNE R2, R3, bench_bad
    RET

check_copy:
    LI R1, DST
    LOAD R2, R1, 0
    LI R3, PATTERN
    BNE R2, R3, bench_bad
    LI R1, DST+BYTES-4
    LOAD R2, R1, 0
    BNE R2, R3, bench_bad
    RET

check_span:
    LI R1, ZBUF
    LOADUH R2, R1, 0
    MOVI R3, 100
    BNE R2, R3, bench_bad
    LI R1, ZBUF+63998
    LOADUH R2, R1, 0
    LI R3, 32099                         ; 100 + 99*320 + 319
    BNE R2, R3, bench_bad
    LI R1, COLOR
    LOADUH R2, R1, 0
    LI R3, COLORVAL
    BNE R2, R3, bench_bad
    RET

bench_bad:
    LI R1, bench_errors
    LOAD R2, R1, 0
    ADDI R2, R2, 1
    STORE R2, R1, 0
    RET

.include "bench.inc"

.data
bench_done:    .word 0
bench_errors:  .word 0
; fill CPU/ROP, copy CPU/ROP, span CPU/ROP.
bench_results: .word 0, 0, 0, 0, 0, 0
