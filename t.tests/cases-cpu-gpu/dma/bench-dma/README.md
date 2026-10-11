# bench-dma

`bench_dma.asm` (código en `bench_dma.inc`) ejecuta cada operación con cada tamaño y cada
configuración, comprueba el resultado, y en la placa mide los ciclos. `bench_dma_report.py` lee los resultados de
la placa y los presenta en tablas.

```text
python cpu_gpu_sim.py t.tests/cases-cpu-gpu/dma/bench-dma/bench_dma.asm
run-board --prototype 36 --port COM3 --program t.tests/cases-cpu-gpu/dma/bench-dma/bench_dma.asm
python t.tests/cases-cpu-gpu/dma/bench-dma/bench_dma_report.py --out tabla.md
```

Tablas y análisis en [bench-dma.md](../../../../32.cpu-gpu-func-sim/docs/bench-dma.md). `run-board` ensambla con `-D BOARD`.
