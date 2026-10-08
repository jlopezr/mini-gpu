; ============================================================
; bench_board.inc - la medida de ciclos en la placa: CYCLES de la CPU
;
; El contador PERF de la CPU (80 MHz) cuenta ciclos mientras la CPU corre, y la
; CPU está esperando a la GPU en gpu_run, así que la diferencia entre dos lecturas
; es el tiempo de pared del trabajo. Una lectura de 32 bits da vueltas cada 53 s;
; la resta de dos lecturas sigue siendo buena aunque dé la vuelta entre medias.
; ============================================================
bench_init:
    RET
bench_now:
    LI    R2, MMIO_CPU_PERF_BASE
    LOAD  R1, R2, MMIO_PERF_CYCLES_OFF
    RET
