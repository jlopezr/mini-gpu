; ============================================================
; poll_exp_perf_sim.inc - los contadores de la GPU en el simulador: no hay
;
; Los simuladores no tienen contadores de rendimiento de la GPU: devuelve ceros y
; el experimento solo sirve para comprobar que los 24 trabajos salen bien.
; ============================================================
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
