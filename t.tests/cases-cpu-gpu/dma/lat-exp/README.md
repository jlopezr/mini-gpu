# lat-exp

`lat_exp.asm` (código en `lat_exp.inc`) mide la latencia de UN acceso: un warp con una sola lane. En el simulador no hay
ciclos y solo comprueba que los 24 trabajos terminan donde deben.

```text
run-board --prototype 36 --port COM3 --program t.tests/cases-cpu-gpu/dma/lat-exp/lat_exp.asm
python t.tests/cases-cpu-gpu/dma/lat-exp/lat_exp_report.py
```

Tablas y análisis en [bench-dma.md](../../../../32.cpu-gpu-func-sim/docs/bench-dma.md). `run-board` ensambla con `-D BOARD`.
