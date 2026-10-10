; ============================================================
; poll_exp_perf.inc - los contadores de rendimiento de la GPU y cómo se lanza el job
;
; Sin BOARD (los simuladores): no hay contadores de rendimiento de la GPU. Devuelve
; ceros y el experimento solo sirve para comprobar que los 24 trabajos salen bien.
;
; Con BOARD (la placa 36): exp_perf_read devuelve R1 = CYCLES, R2 = LSU_TX y
; R3 = STALL_MEM, de la GPU. Solo avanzan con la GPU corriendo (gpu_perf_counters.v).
; ============================================================
.ifdef BOARD
exp_perf_read:
    LI    R4, MMIO_GPU_PERF_BASE
    LOAD  R1, R4, 0x00                      ; CYCLES
    LOAD  R2, R4, 0x10                      ; LSU_TX
    LOAD  R3, R4, 0x14                      ; STALL_MEM
    RET

; exp_perf_read2: R1 = RETIRED (instrucciones de warp), R2 = IMEM_MISSES
exp_perf_read2:
    LI    R4, MMIO_GPU_PERF_BASE
    LOAD  R1, R4, 0x04
    LOAD  R2, R4, 0x0C
    RET

; R10 = base de la GPU. La 36 (hito 1) lanza con RUN: no tiene WARP_START.
exp_launch:
    MOVI  R14, GPU_CTRL_RUN
    STORE R14, R10, MMIO_GPU_CONTROL_OFF
    RET
.else
exp_perf_read:
    MOVI  R1, 0
    MOVI  R2, 0
    MOVI  R3, 0
    RET

exp_perf_read2:
    MOVI  R1, 0
    MOVI  R2, 0
    RET

; R10 = base de la GPU, R7 = los warps del trabajo
exp_launch:
    STORE R7, R10, MMIO_GPU_WARP_START_OFF
    RET
.endif
