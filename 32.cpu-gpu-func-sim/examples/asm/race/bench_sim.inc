; ============================================================
; bench_sim.inc - la medida de ciclos en los simuladores: no hay
;
; Los simuladores cuentan instrucciones, no ciclos, y la CPU y la GPU corren a la
; vez: nada de lo que se pudiera leer aquí sería "el tiempo del trabajo". Se
; devuelve siempre cero y la gráfica de tiempos queda plana. Los ciclos son cosa
; de la placa (bench_board.inc) y del simulador de ciclos de la GPU (carpeta 25).
; ============================================================
bench_init:
    RET
bench_now:
    MOVI  R1, 0
    RET
