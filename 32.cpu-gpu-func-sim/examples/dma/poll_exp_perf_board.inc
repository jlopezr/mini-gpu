; ============================================================
; poll_exp_perf_board.inc - los contadores de rendimiento de la GPU (placa 36)
;
; exp_perf_read devuelve R1 = CYCLES, R2 = LSU_TX y R3 = STALL_MEM, de la GPU. Solo
; avanzan con la GPU corriendo (gpu_perf_counters.v).
; ============================================================
exp_perf_read:
    LI    R4, MMIO_GPU_PERF_BASE
    LOAD  R1, R4, 0x00                      ; CYCLES
    LOAD  R2, R4, 0x10                      ; LSU_TX
    LOAD  R3, R4, 0x14                      ; STALL_MEM
    RET

; R10 = base de la GPU. La 36 (hito 1) lanza con RUN: no tiene WARP_START.
exp_launch:
    MOVI  R14, GPU_CTRL_RUN
    STORE R14, R10, MMIO_GPU_CONTROL_OFF
    RET
