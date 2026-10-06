; ============================================================
; dma.asm - la GPU como memset/memcpy, lanzada por polling desde la CPU
;
; Prueba el protocolo de docs/diseno-gpu-dma.md de extremo a extremo con codigo
; de CPU y de GPU reales. Un solo fichero ensamblable: el runtime y los kernels
; se incluyen aqui, no hay linker.
;
;   python cpu_gpu_sim.py examples\dma\dma.asm
;
; Cinco jobs, de uno en uno. Cada uno deja su estado en la tabla `results`:
;
;   1. memset buf_a = PATTERN, 100 palabras, 2 warps       results[0]  GPU_OK
;      la CPU cuenta cuantas palabras no valen PATTERN      results[1]  0
;   2. memcpy buf_b <- buf_a, 100 palabras, 4 warps         results[2]  GPU_OK
;      palabras erroneas en buf_b                           results[3]  0
;      la palabra justo detras de buf_b (guarda)            results[4]  GUARD
;   3. memset a una direccion fuera de la RAM               results[5]  GPU_ERR_FAULT
;      FIRST_ERROR y FIRST_ERROR_PC de la GPU               results[6], [7]
;   4. un kernel que no termina, con un limite de sondeos   results[8]  GPU_ERR_TIMEOUT
;      corto: HALT y RESET
;   5. memset buf_b = 0 con 1 warp: la GPU se recupero      results[9]  GPU_OK
;      palabras erroneas en buf_b                           results[10] 0
;
; 100 palabras no son multiplo del paso (2 warps x 8 lanes = 16; 4 x 8 = 32), asi
; que la ultima pasada es parcial y las lanes divergen: el caso que hace falta
; el SSY de los kernels.
; ============================================================

.include "mmio.inc"

.equ N,       100                   ; palabras; buf_a y buf_b ocupan 4 * N bytes
.equ PATTERN, 0x11223344
.equ GUARD,   0xDEADBEEF
.equ OUTSIDE, 0x7FFFF000            ; ni RAM ni MMIO: cualquier acceso es error

; R20 = &results, y ningun runtime lo toca (destruyen R1..R15 y R31)
start:
    LI    R20, results

    ; ---- 1. memset buf_a ----
    LI    R3, job_args
    LI    R4, buf_a
    STORE R4, R3, 8
    LI    R4, PATTERN
    STORE R4, R3, 12
    MOVI  R4, N
    STORE R4, R3, 16
    LI    R1, gpu_k_memset
    MOVI  R2, 2
    JAL   R31, gpu_run
    STORE R1, R20, 0

    LI    R1, buf_a
    MOVI  R2, N
    LI    R3, PATTERN
    JAL   R31, check_fill
    STORE R1, R20, 4

    ; ---- 2. memcpy buf_b <- buf_a ----
    LI    R3, job_args
    LI    R4, buf_b
    STORE R4, R3, 8
    LI    R4, buf_a
    STORE R4, R3, 12
    MOVI  R4, N
    STORE R4, R3, 16
    LI    R1, gpu_k_memcpy
    MOVI  R2, 4
    JAL   R31, gpu_run
    STORE R1, R20, 8

    LI    R1, buf_b
    MOVI  R2, N
    LI    R3, PATTERN
    JAL   R31, check_fill
    STORE R1, R20, 12

    LI    R4, guard
    LOAD  R4, R4, 0
    STORE R4, R20, 16

    ; ---- 3. memset fuera de la RAM: la GPU para con error ----
    LI    R3, job_args
    LI    R4, OUTSIDE
    STORE R4, R3, 8
    LI    R4, PATTERN
    STORE R4, R3, 12
    MOVI  R4, N
    STORE R4, R3, 16
    LI    R1, gpu_k_memset
    MOVI  R2, 1
    JAL   R31, gpu_run
    STORE R1, R20, 20
    STORE R2, R20, 24
    STORE R3, R20, 28

    ; ---- 4. un kernel que no termina: limite corto de sondeos ----
    LI    R4, gpu_timeout_polls
    MOVI  R5, 200
    STORE R5, R4, 0
    LI    R3, job_args
    LI    R1, gpu_k_hang
    MOVI  R2, 1
    JAL   R31, gpu_run
    STORE R1, R20, 32
    LI    R4, gpu_timeout_polls
    MOVI  R5, GPU_TIMEOUT_POLLS
    STORE R5, R4, 0

    ; ---- 5. tras el error y el timeout, la GPU sigue sirviendo ----
    LI    R3, job_args
    LI    R4, buf_b
    STORE R4, R3, 8
    STORE R0, R3, 12                ; valor 0
    MOVI  R4, N
    STORE R4, R3, 16
    LI    R1, gpu_k_memset
    MOVI  R2, 1
    JAL   R31, gpu_run
    STORE R1, R20, 36

    LI    R1, buf_b
    MOVI  R2, N
    MOVI  R3, 0
    JAL   R31, check_fill
    STORE R1, R20, 40
    HALT

; ---- check_fill: R1 = ptr, R2 = nwords, R3 = valor -> R1 = palabras distintas ----
check_fill:
    MOVI  R4, 0
check_fill_loop:
    BEQ   R2, R0, check_fill_end
    LOAD  R5, R1, 0
    BEQ   R5, R3, check_fill_same
    ADDI  R4, R4, 1
check_fill_same:
    ADDI  R1, R1, 4
    ADDI  R2, R2, -1
    BRA   check_fill_loop
check_fill_end:
    ADD   R1, R4, R0
    RET

; ---- el runtime de CPU y los kernels de GPU: una sola imagen ----
.include "gpu_runtime.inc"
.include "gpu_kernels.inc"

; kernel de prueba, solo para el job 4: no acaba nunca
gpu_k_hang:
    BRA   gpu_k_hang

; ---- datos: lo ultimo de la imagen ----
job_args:
    .space 32
results:
    .space 44
buf_a:
    .space 400                      ; 4 * N
buf_b:
    .space 400
guard:
    .word GUARD
