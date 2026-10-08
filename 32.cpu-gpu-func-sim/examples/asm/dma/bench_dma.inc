; ============================================================
; bench_dma.inc - benchmark de memset, memcpy, fill_rect y blit: CPU contra GPU
;
; Para cada operación, cada tamaño (32 B a 1 MiB) y cada configuración (la CPU sola
; y la GPU con 1, 2, 4 y 8 warps) mide los ciclos de CPU que tarda, y se queda con
; el mejor de `bench_reps` repeticiones. En la GPU cuenta el trabajo entero, como lo
; ve el programa: preparar el bloque de argumentos, escribir los descriptores,
; lanzar y sondear hasta el fin (gpu_run). Es lo que decide si merece la pena
; mandarlo a la GPU, y por eso incluye el coste fijo de cada lanzamiento.
;
; Las formas de las operaciones, para S bytes = N palabras:
;
;     memset, memcpy   N palabras seguidas
;     fill_rect, blit  filas de min(N, 64) palabras (hasta 256 B), N / eso filas,
;                      en un pitch de destino de 640 bytes (una pantalla de 320
;                      píxeles de 16 bits); el blit lee de un origen contiguo
;
; La CPU usa bucles desenrollados de cuatro palabras: es la CPU honesta, no una
; de paja. Tras cada operación se comprueba la primera y la última palabra del
; destino (que se ponen a cero antes): `bench_errors` cuenta los fallos.
;
; Los resultados quedan en memoria, juntos y en este orden, para leerlos con
; `monitor.py read-block` (808 bytes desde `bench_done`):
;
;     bench_done      1 cuando ha terminado
;     bench_errors    comprobaciones fallidas
;     bench_results   (operación * 10 + tamaño) * 5 + configuración, en ciclos
;
; Quién cuenta los ciclos, en bench_sim.inc / bench_board.inc: el simulador devuelve
; cero (solo sirve para comprobar que todo funciona) y la placa lee el CYCLES de la CPU.
; ============================================================

.equ BENCH_SRC,       0x00200000
.equ BENCH_DST,       0x00600000
.equ BENCH_VALUE,     0xA5A5A5A5
.equ BENCH_SRC_WORDS, 262144        ; 1 MiB
.equ BENCH_PITCH,     640

; R16 operación (0 memset, 1 memcpy, 2 fill_rect, 3 blit)   R17 índice de tamaño
; R18 configuración (0 CPU, 1..4 GPU con 1, 2, 4, 8 warps)  R19 repeticiones que quedan
; R20 mejor tiempo   R21 palabras   R23 palabras por fila   R24 filas
; R25 ciclos al empezar   R27 dirección de la última palabra del destino
; R28 lo que debe valer la última   R29 lo que debe valer la primera   R30 retorno de bench_run
start:
    LI    R4, MMIO_GPU_BASE
    MOVI  R5, GPU_CTRL_RESET
    STORE R5, R4, MMIO_GPU_CONTROL_OFF      ; la placa conserva el estado de la GPU

    LI    R4, gpu_timeout_polls
    LI    R5, 8000000
    STORE R5, R4, 0                         ; 1 MiB con un solo warp tarda lo suyo

    JAL   R31, bench_init
    JAL   R31, bench_fill_src

    MOVI  R16, 0
bench_op:
    MOVI  R17, 0
bench_size:
    JAL   R31, bench_geometry
    MOVI  R18, 0
bench_cfg:
    LI    R4, bench_reps
    LOAD  R19, R4, 0
    LI    R20, 0xFFFFFFFF
bench_rep:
    JAL   R31, bench_clear
    JAL   R31, bench_now
    ADDI  R25, R1, 0
    JAL   R31, bench_run
    JAL   R31, bench_now
    SUB   R1, R1, R25                       ; ciclos de esta repetición
    BGEU  R1, R20, bench_keep
    ADDI  R20, R1, 0                        ; el mejor hasta ahora
bench_keep:
    JAL   R31, bench_check
    ADDI  R19, R19, -1
    BNE   R19, R0, bench_rep

    MOVI  R4, 10                            ; bench_results[(op * 10 + tamaño) * 5 + config]
    MUL   R4, R16, R4
    ADD   R4, R4, R17
    MOVI  R5, 5
    MUL   R4, R4, R5
    ADD   R4, R4, R18
    SHLI  R4, R4, 2
    LI    R5, bench_results
    ADD   R4, R4, R5
    STORE R20, R4, 0

    ADDI  R18, R18, 1
    MOVI  R4, 5
    BLT   R18, R4, bench_cfg
    ADDI  R17, R17, 1
    LI    R4, bench_nsizes
    LOAD  R4, R4, 0
    BLT   R17, R4, bench_size
    ADDI  R16, R16, 1
    MOVI  R4, 4
    BLT   R16, R4, bench_op

    LI    R4, bench_done
    MOVI  R5, 1
    STORE R5, R4, 0
    HALT

; ---- el origen: palabra i = i * 0x9E3779B1 + 0x1234567, para que ninguna sea cero ----
bench_fill_src:
    LI    R1, BENCH_SRC
    MOVI  R2, 0
    LI    R3, BENCH_SRC_WORDS
    LI    R5, 0x9E3779B1
    LI    R6, 0x1234567
bench_fill_loop:
    MUL   R4, R2, R5
    ADD   R4, R4, R6
    STORE R4, R1, 0
    ADDI  R1, R1, 4
    ADDI  R2, R2, 1
    BLT   R2, R3, bench_fill_loop
    RET

; ---- la forma de la operación y lo que se espera ----
bench_geometry:
    LI    R4, bench_sizes
    SHLI  R5, R17, 2
    ADD   R4, R4, R5
    LOAD  R5, R4, 0                         ; bytes
    SHRI  R21, R5, 2                        ; palabras
    MOVI  R23, 64
    BLT   R21, R23, bench_geo_small
    BRA   bench_geo_rows
bench_geo_small:
    ADDI  R23, R21, 0                       ; una sola fila
bench_geo_rows:
    DIVU  R24, R21, R23                     ; filas
    LI    R27, BENCH_DST
    MOVI  R4, 2
    BLT   R16, R4, bench_geo_lin
    ADDI  R4, R24, -1                       ; rectángulo: DST + (filas - 1) * pitch + 4 * (fila - 1)
    MOVI  R5, BENCH_PITCH
    MUL   R4, R4, R5
    ADD   R27, R27, R4
    ADDI  R4, R23, -1
    SHLI  R4, R4, 2
    ADD   R27, R27, R4
    BRA   bench_geo_exp
bench_geo_lin:
    ADDI  R4, R21, -1                       ; lineal: DST + 4 * (N - 1)
    SHLI  R4, R4, 2
    ADD   R27, R27, R4
bench_geo_exp:
    LI    R28, BENCH_VALUE                  ; memset y fill_rect dejan el valor
    ADDI  R29, R28, 0
    ANDI  R4, R16, 1
    BEQ   R4, R0, bench_geo_done
    LI    R4, BENCH_SRC                     ; memcpy y blit dejan el origen, contiguo
    LOAD  R29, R4, 0
    ADDI  R5, R21, -1
    SHLI  R5, R5, 2
    ADD   R4, R4, R5
    LOAD  R28, R4, 0
bench_geo_done:
    RET

; ---- antes de cada repetición, a cero las dos palabras que se comprueban ----
bench_clear:
    LI    R4, BENCH_DST
    STORE R0, R4, 0
    STORE R0, R27, 0
    RET

bench_check:
    LI    R4, BENCH_DST
    LOAD  R5, R4, 0
    BNE   R5, R29, bench_bad
    LOAD  R5, R27, 0
    BNE   R5, R28, bench_bad
    RET
bench_bad:
    LI    R4, bench_errors
    LOAD  R5, R4, 0
    ADDI  R5, R5, 1
    STORE R5, R4, 0
    RET

; ---- una operación, con la configuración de R18 ----
bench_run:
    ADDI  R30, R31, 0
    BNE   R18, R0, bench_run_gpu
    MOVI  R4, 1
    BLT   R16, R4, bench_c0
    BEQ   R16, R4, bench_c1
    MOVI  R4, 2
    BEQ   R16, R4, bench_c2
    JAL   R31, bench_cpu_blit
    JR    R30
bench_c0:
    JAL   R31, bench_cpu_memset
    JR    R30
bench_c1:
    JAL   R31, bench_cpu_memcpy
    JR    R30
bench_c2:
    JAL   R31, bench_cpu_fill_rect
    JR    R30

bench_run_gpu:
    LI    R3, job_args
    LI    R4, BENCH_DST
    STORE R4, R3, 8                         ; p0 = dst, en las cuatro
    MOVI  R5, 1
    BLT   R16, R5, bench_g0
    BEQ   R16, R5, bench_g1
    MOVI  R5, 2
    BEQ   R16, R5, bench_g2
    MOVI  R5, BENCH_PITCH                   ; blit
    STORE R5, R3, 12
    LI    R5, BENCH_SRC
    STORE R5, R3, 16
    SHLI  R5, R23, 2
    STORE R5, R3, 20                        ; src_pitch: el origen es contiguo
    STORE R23, R3, 24
    STORE R24, R3, 28
    LI    R1, gpu_k_blit
    BRA   bench_launch
bench_g0:
    LI    R5, BENCH_VALUE
    STORE R5, R3, 12
    STORE R21, R3, 16
    LI    R1, gpu_k_memset
    BRA   bench_launch
bench_g1:
    LI    R5, BENCH_SRC
    STORE R5, R3, 12
    STORE R21, R3, 16
    LI    R1, gpu_k_memcpy
    BRA   bench_launch
bench_g2:
    MOVI  R5, BENCH_PITCH
    STORE R5, R3, 12
    STORE R23, R3, 16
    STORE R24, R3, 20
    LI    R5, BENCH_VALUE
    STORE R5, R3, 24
    LI    R1, gpu_k_fill_rect
bench_launch:
    MOVI  R2, 1
    ADDI  R4, R18, -1
    SHL   R2, R2, R4                        ; 1, 2, 4 u 8 warps
    LI    R3, job_args
    JAL   R31, gpu_run
    BEQ   R1, R0, bench_run_ok
    LI    R4, bench_errors                  ; un trabajo que falla cuenta como error
    LOAD  R5, R4, 0
    ADDI  R5, R5, 1
    STORE R5, R4, 0
bench_run_ok:
    JR    R30

; ---- la CPU: bucles de cuatro palabras ----
bench_cpu_memset:
    LI    R1, BENCH_DST
    LI    R2, BENCH_VALUE
    ADDI  R3, R21, 0
bench_cpu_memset_loop:
    STORE R2, R1, 0
    STORE R2, R1, 4
    STORE R2, R1, 8
    STORE R2, R1, 12
    ADDI  R1, R1, 16
    ADDI  R3, R3, -4
    BNE   R3, R0, bench_cpu_memset_loop
    RET

bench_cpu_memcpy:
    LI    R1, BENCH_DST
    LI    R2, BENCH_SRC
    ADDI  R3, R21, 0
bench_cpu_memcpy_loop:
    LOAD  R4, R2, 0
    LOAD  R5, R2, 4
    LOAD  R6, R2, 8
    LOAD  R7, R2, 12
    STORE R4, R1, 0
    STORE R5, R1, 4
    STORE R6, R1, 8
    STORE R7, R1, 12
    ADDI  R1, R1, 16
    ADDI  R2, R2, 16
    ADDI  R3, R3, -4
    BNE   R3, R0, bench_cpu_memcpy_loop
    RET

bench_cpu_fill_rect:
    LI    R1, BENCH_DST
    LI    R2, BENCH_VALUE
    ADDI  R8, R24, 0                        ; filas
bench_cpu_fill_row:
    ADDI  R9, R1, 0
    ADDI  R3, R23, 0
bench_cpu_fill_col:
    STORE R2, R9, 0
    STORE R2, R9, 4
    STORE R2, R9, 8
    STORE R2, R9, 12
    ADDI  R9, R9, 16
    ADDI  R3, R3, -4
    BNE   R3, R0, bench_cpu_fill_col
    ADDI  R1, R1, BENCH_PITCH
    ADDI  R8, R8, -1
    BNE   R8, R0, bench_cpu_fill_row
    RET

bench_cpu_blit:
    LI    R1, BENCH_DST
    LI    R2, BENCH_SRC
    ADDI  R8, R24, 0
bench_cpu_blit_row:
    ADDI  R9, R1, 0
    ADDI  R3, R23, 0
bench_cpu_blit_col:
    LOAD  R4, R2, 0
    LOAD  R5, R2, 4
    LOAD  R6, R2, 8
    LOAD  R7, R2, 12
    STORE R4, R9, 0
    STORE R5, R9, 4
    STORE R6, R9, 8
    STORE R7, R9, 12
    ADDI  R9, R9, 16
    ADDI  R2, R2, 16
    ADDI  R3, R3, -4
    BNE   R3, R0, bench_cpu_blit_col
    ADDI  R1, R1, BENCH_PITCH
    ADDI  R8, R8, -1
    BNE   R8, R0, bench_cpu_blit_row
    RET

; ---- datos ----
bench_sizes:
    .word 32, 64, 128, 256, 1024, 4096, 16384, 65536, 262144, 1048576
bench_nsizes:
    .word 10
bench_reps:
    .word 3
; bench_done, bench_errors y bench_results, seguidos: se leen de una vez
bench_done:
    .word 0
bench_errors:
    .word 0
bench_results:
    .space 800                                  ; 4 operaciones * 10 tamaños * 5 configuraciones
job_args:
    .space 32
