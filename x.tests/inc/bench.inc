; ============================================================
; bench.inc - la medida de ciclos de CPU: bench_init y bench_now
;
; En los simuladores no hay: cuentan instrucciones, no ciclos, y la CPU y la GPU
; corren a la vez, asi que nada de lo que se pudiera leer aqui seria "el tiempo
; del trabajo". bench_now devuelve siempre cero y la grafica de tiempos queda
; plana. Los ciclos son cosa de la placa y del simulador de ciclos de la GPU
; (carpeta 25).
;
; Con `.define BOARD` (o `-D BOARD`) antes del `.include`: la placa. El contador
; PERF de la CPU (80 MHz) cuenta ciclos mientras la CPU corre, y la CPU esta
; esperando a la GPU en gpu_run, asi que la diferencia entre dos lecturas es el
; tiempo de pared del trabajo. Una lectura de 32 bits da vueltas cada 53 s; la
; resta de dos lecturas sigue siendo buena aunque de la vuelta entre medias.
; ============================================================
bench_init:
    RET
bench_now:
.ifdef BOARD
    LI    R2, MMIO_CPU_PERF_BASE
    LOAD  R1, R2, MMIO_PERF_CYCLES_OFF
.else
    MOVI  R1, 0
.endif
    RET
