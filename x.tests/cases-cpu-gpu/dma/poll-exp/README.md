# poll-exp

`poll_exp.asm` (código en `poll_exp.inc`) lanza `memset` y `memcpy` de 256 KiB con 1, 2, 4 y 8 warps y espera de tres
maneras. En la placa mide con los contadores de rendimiento de la propia GPU, que no dependen de cómo espere la CPU.

```text
run-board --prototype 36 --port COM3 --program x.tests/cases-cpu-gpu/dma/poll-exp/poll_exp.asm
python x.tests/cases-cpu-gpu/dma/poll-exp/poll_exp_report.py
```

Tablas y análisis en [bench-dma.md](../../../../32.cpu-gpu-func-sim/docs/bench-dma.md). `run-board` ensambla con `-D BOARD`.
