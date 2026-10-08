; ============================================================
; lat_exp.inc - ¿cuánto tarda UNA transacción de la GPU, y de qué depende?
;
; poll_exp.inc dejó una cifra: con la memoria saturada, una transacción de 16 B cuesta
; ~38 ciclos de GPU (25 MHz) en `memset` y ~30 en `memcpy`, y el simulador de ciclos
; suponía 17. El sondeo de la CPU no lo explica. Quedan dos sitios: la LSU (que atiende
; las transacciones de una en una, con un coste fijo) o la SDRAM (cambiar de fila cuesta
; más que seguir en la misma).
;
; Para separarlos, un solo warp con una sola lane hace N accesos DEPENDIENTES uno
; detrás de otro, con distintas separaciones entre direcciones (stride): 0 (siempre la
; misma), 16 (líneas seguidas), y de ahí hasta 64 KiB (cada acceso, en otra fila). Si el
; coste por acceso es el mismo con todas, el límite está en la LSU; si crece con la
; separación, en la SDRAM.
;
; Tres kernels con el mismo bucle: `lat_k_alu` no toca la memoria (es la línea base:
; lo que cuestan las instrucciones del bucle), `lat_k_load` lee y suma lo leído, y
; `lat_k_store` escribe. La latencia de un acceso es (ciclos con acceso - ciclos de la
; línea base) / N. Se mide con los contadores de rendimiento de la GPU (CYCLES y
; LSU_TX), que solo avanzan con la GPU corriendo.
;
; Cada fila de `lat_results` son cinco palabras: ciclos de GPU, transacciones, N,
; instrucciones de warp retiradas y fallos del búfer de instrucciones. La fila es
; kernel * 8 + índice de stride (lat_strides).
; ============================================================

.equ LAT_BASE,   0x00600000
.equ LAT_VALUE,  0x1234ABCD

start:
    LI    R4, MMIO_GPU_BASE
    MOVI  R5, GPU_CTRL_RESET
    STORE R5, R4, MMIO_GPU_CONTROL_OFF
    JAL   R31, bench_init

    MOVI  R24, 0                            ; kernel: 0 alu, 1 load, 2 store
lat_kernel:
    MOVI  R25, 0                            ; índice de stride
lat_stride:
    JAL   R31, lat_prepare
    JAL   R31, lat_run
    JAL   R31, lat_store_row
    ADDI  R25, R25, 1
    MOVI  R4, 8
    BLT   R25, R4, lat_stride
    ADDI  R24, R24, 1
    MOVI  R4, 3
    BLT   R24, R4, lat_kernel

    LI    R4, lat_done
    MOVI  R5, 1
    STORE R5, R4, 0
    HALT

; ---- el kernel, el bloque de argumentos y N para (R24, R25) ----
; R16 = kernel   R17 = stride   R18 = N
lat_prepare:
    SHLI  R4, R25, 2
    LI    R5, lat_strides
    ADD   R5, R5, R4
    LOAD  R17, R5, 0
    LI    R5, lat_counts
    ADD   R5, R5, R4
    LOAD  R18, R5, 0
    LI    R3, job_args
    LI    R4, LAT_BASE
    STORE R4, R3, 8                         ; p0 = base
    STORE R17, R3, 12                       ; p1 = stride
    STORE R18, R3, 16                       ; p2 = N
    LI    R16, lat_k_alu
    BEQ   R24, R0, lat_prep_done
    LI    R16, lat_k_load
    MOVI  R4, 1
    BEQ   R24, R4, lat_prep_done
    LI    R16, lat_k_store
lat_prep_done:
    RET

; ---- lanza un warp con UNA lane activa y espera ----
lat_run:
    ADDI  R30, R31, 0
    JAL   R31, exp_perf_read
    ADDI  R20, R1, 0
    ADDI  R21, R2, 0
    JAL   R31, exp_perf_read2
    ADDI  R27, R1, 0
    ADDI  R28, R2, 0
    LI    R10, MMIO_GPU_BASE
    LI    R11, MMIO_GPU_WARPS_BASE
    LI    R3, job_args
    MOVI  R4, 1
    STORE R4, R3, 0                         ; nwarps = 1
    MOVI  R4, 8
    STORE R4, R3, 4                         ; nlanes
    STORE R16, R11, MMIO_GPU_WARPS_PC_OFF
    MOVI  R4, 1
    STORE R4, R11, MMIO_GPU_WARPS_ACTIVE_OFF    ; solo la lane 0
    STORE R4, R11, MMIO_GPU_WARPS_GROUP_OFF
    STORE R0, R11, MMIO_GPU_WARPS_LOGICAL_ID_OFF
    STORE R3, R11, MMIO_GPU_WARPS_ARG_OFF
    MOVI  R7, 1                             ; el warp pendiente
    JAL   R31, exp_launch
lat_poll:
    LOAD  R5, R10, MMIO_GPU_STATUS_OFF
    LOAD  R6, R10, MMIO_GPU_WARP_DONE_OFF
    BEQ   R6, R0, lat_poll
    STORE R6, R10, MMIO_GPU_WARP_DONE_OFF
    JAL   R31, exp_perf_read
    SUB   R1, R1, R20
    SUB   R2, R2, R21
    LI    R4, lat_cur
    STORE R1, R4, 0
    STORE R2, R4, 4
    JAL   R31, exp_perf_read2
    SUB   R1, R1, R27
    SUB   R2, R2, R28
    LI    R4, lat_cur
    STORE R1, R4, 8
    STORE R2, R4, 12
    JR    R30

lat_store_row:
    MOVI  R4, 8
    MUL   R4, R24, R4
    ADD   R4, R4, R25
    MOVI  R5, 20
    MUL   R4, R4, R5
    LI    R5, lat_results
    ADD   R4, R4, R5
    LI    R5, lat_cur
    LOAD  R6, R5, 0
    STORE R6, R4, 0
    LOAD  R6, R5, 4
    STORE R6, R4, 4
    STORE R18, R4, 8
    LOAD  R6, R5, 8
    STORE R6, R4, 12
    LOAD  R6, R5, 12
    STORE R6, R4, 16
    RET

; ---- los tres kernels: una lane, N vueltas ----
; R4 dirección   R5 stride   R6 vueltas que quedan   R7 acumulador   R8 lo leído
lat_k_alu:
    GETARG   R1
    LOAD     R4, R1, 8
    LOAD     R5, R1, 12
    LOAD     R6, R1, 16
    MOVI     R7, 0
lat_alu_loop:
    ADD      R8, R4, R0                     ; en vez del acceso
    ADD      R7, R7, R8
    ADD      R4, R4, R5
    ADDI     R6, R6, -1
    BNE      R6, R0, lat_alu_loop
    EXIT

lat_k_load:
    GETARG   R1
    LOAD     R4, R1, 8
    LOAD     R5, R1, 12
    LOAD     R6, R1, 16
    MOVI     R7, 0
lat_load_loop:
    LOAD     R8, R4, 0
    ADD      R7, R7, R8                     ; usa lo leído: el siguiente acceso lo espera
    ADD      R4, R4, R5
    ADDI     R6, R6, -1
    BNE      R6, R0, lat_load_loop
    EXIT

lat_k_store:
    GETARG   R1
    LOAD     R4, R1, 8
    LOAD     R5, R1, 12
    LOAD     R6, R1, 16
    LI       R9, LAT_VALUE
    MOVI     R7, 0
lat_store_loop:
    STORE    R9, R4, 0
    ADD      R7, R7, R4
    ADD      R4, R4, R5
    ADDI     R6, R6, -1
    BNE      R6, R0, lat_store_loop
    EXIT

; ---- datos: lat_done y lat_results seguidos (4 + 24 * 20 bytes) ----
lat_done:
    .word 0
lat_results:
    .space 480
lat_cur:
    .space 16
lat_strides:
    .word 0, 16, 64, 256, 1024, 4096, 16384, 65536
lat_counts:
    .word 2000, 2000, 2000, 2000, 2000, 2000, 512, 128      ; N * stride <= 8 MiB
job_args:
    .space 32
