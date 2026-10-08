; ============================================================
; poll_exp.inc - ¿el sondeo de la CPU frena a la GPU?
;
; El benchmark (bench_dma.inc) sacó que la GPU escribe a ~10 MB/s: unos 38 ciclos
; de GPU por transacción de 16 B, contra los 17 que suponía el simulador de ciclos.
; Una hipótesis es que la CPU, que mientras espera lee sin parar STATUS y WARP_DONE
; del MMIO de la GPU, le quite tiempo al puente entre los dos relojes.
;
; Aquí se lanza el mismo trabajo con tres maneras de esperar y se mide con los
; contadores de rendimiento DE LA GPU (CYCLES, LSU_TX y STALL_MEM, que solo
; avanzan con la GPU corriendo), así que no dependen de cómo espere la CPU:
;
;     modo 0  sondea sin parar (lo que hace gpu_run)
;     modo 1  sondea con una pausa de ~200 iteraciones (~40 µs) entre lecturas
;     modo 2  no toca el MMIO de la GPU hasta pasados ~190 ms, y entonces lo lee
;
; Si el sondeo frenara a la GPU, los ciclos de GPU por transacción bajarían del
; modo 0 al modo 2.
;
; Trabajos: memset y memcpy de 256 KiB, con 1, 2, 4 y 8 warps: 2 x 4 x 3 = 24 medidas.
; Cada fila de `exp_results` son cuatro palabras:
;
;     ciclos de GPU   transacciones de la LSU   ciclos de GPU esperando a memoria   ciclos de CPU
;
; La fila es (operación * 4 + warps) * 3 + modo. Mira poll_exp_report.py.
; ============================================================

.equ EXP_SRC,    0x00200000
.equ EXP_DST,    0x00600000
.equ EXP_WORDS,  65536                      ; 256 KiB
.equ EXP_VALUE,  0xA5A5A5A5
.equ EXP_INITIAL, 1000000                   ; modo 2: ~15 ciclos por iteración -> ~190 ms
.equ EXP_GAP,    200                        ; modo 1

; R16 kernel   R17 nwarps   R18 pausa entre sondeos   R19 espera inicial
; R20..R22 contadores de la GPU antes   R23 ciclos de CPU al empezar
; R24 operación   R25 índice de warps   R26 modo   R30 retorno de exp_run
start:
    LI    R4, MMIO_GPU_BASE
    MOVI  R5, GPU_CTRL_RESET
    STORE R5, R4, MMIO_GPU_CONTROL_OFF
    JAL   R31, bench_init
    JAL   R31, exp_fill_src

    MOVI  R24, 0
exp_op:
    MOVI  R25, 0
exp_warps:
    MOVI  R26, 0
exp_mode:
    JAL   R31, exp_prepare                  ; bloque de argumentos y kernel de esta operación
    JAL   R31, bench_now
    ADDI  R23, R1, 0
    JAL   R31, exp_run
    JAL   R31, bench_now
    SUB   R23, R1, R23                      ; ciclos de CPU de la medida
    JAL   R31, exp_check
    JAL   R31, exp_store
    ADDI  R26, R26, 1
    MOVI  R4, 3
    BLT   R26, R4, exp_mode
    ADDI  R25, R25, 1
    MOVI  R4, 4
    BLT   R25, R4, exp_warps
    ADDI  R24, R24, 1
    MOVI  R4, 2
    BLT   R24, R4, exp_op

    LI    R4, exp_done
    MOVI  R5, 1
    STORE R5, R4, 0
    HALT

exp_fill_src:
    LI    R1, EXP_SRC
    MOVI  R2, 0
    LI    R3, EXP_WORDS
    LI    R5, 0x9E3779B1
    LI    R6, 0x1234567
exp_fill_loop:
    MUL   R4, R2, R5
    ADD   R4, R4, R6
    STORE R4, R1, 0
    ADDI  R1, R1, 4
    ADDI  R2, R2, 1
    BLT   R2, R3, exp_fill_loop
    RET

; ---- kernel, warps, pausas y bloque de argumentos para (R24, R25, R26) ----
exp_prepare:
    MOVI  R17, 1
    SHL   R17, R17, R25                     ; 1, 2, 4, 8 warps
    MOVI  R18, 0
    MOVI  R19, 0
    MOVI  R4, 1
    BEQ   R26, R4, exp_prep_gap
    MOVI  R4, 2
    BNE   R26, R4, exp_prep_args
    LI    R19, exp_initial_cfg              ; modo 2 (un dato, para que el test lo acorte)
    LOAD  R19, R19, 0
    BRA   exp_prep_args
exp_prep_gap:
    MOVI  R18, EXP_GAP                      ; modo 1
exp_prep_args:
    LI    R3, job_args
    LI    R4, EXP_DST
    STORE R4, R3, 8                         ; p0 = dst
    BNE   R24, R0, exp_prep_copy
    LI    R4, EXP_VALUE                     ; memset: p1 = valor, p2 = palabras
    STORE R4, R3, 12
    LI    R4, EXP_WORDS
    STORE R4, R3, 16
    LI    R16, gpu_k_memset
    RET
exp_prep_copy:
    LI    R4, EXP_SRC                       ; memcpy: p1 = src, p2 = palabras
    STORE R4, R3, 12
    LI    R4, EXP_WORDS
    STORE R4, R3, 16
    LI    R16, gpu_k_memcpy
    RET

; ---- lanza y espera, como gpu_run pero con las pausas de R18 y R19 ----
; Deja en exp_cur los cuatro deltas de la GPU: ciclos, transacciones, espera de memoria.
exp_run:
    ADDI  R30, R31, 0
    LI    R4, EXP_DST                       ; las dos palabras que se comprueban, a cero
    STORE R0, R4, 0
    LI    R5, EXP_WORDS
    ADDI  R5, R5, -1
    SHLI  R5, R5, 2
    ADD   R4, R4, R5
    STORE R0, R4, 0

    JAL   R31, exp_perf_read
    ADDI  R20, R1, 0
    ADDI  R21, R2, 0
    ADDI  R22, R3, 0

    LI    R10, MMIO_GPU_BASE
    LI    R11, MMIO_GPU_WARPS_BASE
    LI    R3, job_args
    STORE R17, R3, 0                        ; nwarps
    MOVI  R4, 8
    STORE R4, R3, 4                         ; nlanes
    MOVI  R7, 1
    SHL   R7, R7, R17
    ADDI  R7, R7, -1                        ; warps pendientes
    MOVI  R8, 255                           ; ACTIVE: las ocho lanes
    MOVI  R15, 1                            ; id del trabajo
    MOVI  R9, 0
    MOVI  R12, 0
    MOVI  R13, 0
exp_desc:
    ADD   R14, R11, R12
    STORE R16, R14, MMIO_GPU_WARPS_PC_OFF
    STORE R8, R14, MMIO_GPU_WARPS_ACTIVE_OFF
    STORE R15, R14, MMIO_GPU_WARPS_GROUP_OFF
    ADD   R14, R11, R13
    STORE R9, R14, MMIO_GPU_WARPS_LOGICAL_ID_OFF
    STORE R3, R14, MMIO_GPU_WARPS_ARG_OFF
    ADDI  R9, R9, 1
    ADDI  R12, R12, MMIO_GPU_WARPS_STRIDE
    ADDI  R13, R13, 4
    BLTU  R9, R17, exp_desc

    JAL   R31, exp_launch                   ; WARP_START en el simulador, RUN en la placa
    ADDI  R4, R19, 0                        ; espera inicial: sin tocar el MMIO de la GPU
exp_initial:
    BEQ   R4, R0, exp_poll
    ADDI  R4, R4, -1
    BRA   exp_initial
exp_poll:
    LOAD  R5, R10, MMIO_GPU_STATUS_OFF
    LOAD  R6, R10, MMIO_GPU_WARP_DONE_OFF
    BEQ   R6, R0, exp_check_pending
    STORE R6, R10, MMIO_GPU_WARP_DONE_OFF
    AND   R14, R7, R6
    XOR   R7, R7, R14
exp_check_pending:
    BEQ   R7, R0, exp_finished
    ADDI  R4, R18, 0                        ; pausa entre sondeos
exp_gap:
    BEQ   R4, R0, exp_poll
    ADDI  R4, R4, -1
    BRA   exp_gap
exp_finished:
    JAL   R31, exp_perf_read
    SUB   R1, R1, R20
    SUB   R2, R2, R21
    SUB   R3, R3, R22
    LI    R4, exp_cur
    STORE R1, R4, 0
    STORE R2, R4, 4
    STORE R3, R4, 8
    JR    R30

; ---- la comprobación: primera y última palabra del destino ----
exp_check:
    LI    R4, EXP_DST
    LOAD  R5, R4, 0
    LI    R6, EXP_VALUE
    BNE   R24, R0, exp_chk_copy
    BNE   R5, R6, exp_bad
    BRA   exp_chk_last
exp_chk_copy:
    LI    R7, EXP_SRC
    LOAD  R7, R7, 0
    BNE   R5, R7, exp_bad
    LI    R6, EXP_SRC
    LI    R7, EXP_WORDS
    ADDI  R7, R7, -1
    SHLI  R7, R7, 2
    ADD   R6, R6, R7
    LOAD  R6, R6, 0                         ; src[N-1]
exp_chk_last:
    LI    R4, EXP_DST
    LI    R7, EXP_WORDS
    ADDI  R7, R7, -1
    SHLI  R7, R7, 2
    ADD   R4, R4, R7
    LOAD  R5, R4, 0
    BNE   R5, R6, exp_bad
    RET
exp_bad:
    LI    R4, exp_errors
    LOAD  R5, R4, 0
    ADDI  R5, R5, 1
    STORE R5, R4, 0
    RET

; ---- guarda la fila ----
exp_store:
    MOVI  R4, 4
    MUL   R4, R24, R4
    ADD   R4, R4, R25
    MOVI  R5, 3
    MUL   R4, R4, R5
    ADD   R4, R4, R26
    SHLI  R4, R4, 4
    LI    R5, exp_results
    ADD   R4, R4, R5
    LI    R5, exp_cur
    LOAD  R6, R5, 0
    STORE R6, R4, 0
    LOAD  R6, R5, 4
    STORE R6, R4, 4
    LOAD  R6, R5, 8
    STORE R6, R4, 8
    STORE R23, R4, 12
    RET

; ---- datos: exp_done, exp_errors y exp_results, seguidos (8 + 24 * 16 bytes) ----
exp_done:
    .word 0
exp_errors:
    .word 0
exp_results:
    .space 384
exp_cur:
    .space 12
exp_initial_cfg:
    .word EXP_INITIAL
job_args:
    .space 32
