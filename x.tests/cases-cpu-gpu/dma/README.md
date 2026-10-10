# dma

[`harness/dma.asm`](harness/dma.asm) es el arnés del diseño de
[`diseno-gpu-dma.md`](../../../32.cpu-gpu-func-sim/docs/diseno-gpu-dma.md): la GPU como `memset` y
`memcpy`, lanzada por polling desde un runtime de CPU (`x.tests/inc/gpu_runtime.inc`) con los
kernels en `gpu_kernels.inc`, todo en una sola imagen. Incluye un job que falla,
uno que no termina y la recuperación de la GPU.

## Kernels de sistema y su benchmark

`gpu_kernels.inc` tiene los kernels de [`diseno-gpu-dma.md`](../../../32.cpu-gpu-func-sim/docs/diseno-gpu-dma.md) §7: `memset`, `memcpy`,
`fill_rect` y `blit` (falta `convert`). `rect.asm` ejercita `fill_rect` y `blit` con
geometrías incómodas y `bench_dma.asm` los cuatro, con todas las configuraciones,
comprobando el resultado. En la placa, `bench_dma.asm` (con `run-board`) y `bench_dma_report.py`
miden cada operación con cada tamaño (32 B a 1 MiB) en la CPU y en la GPU con 1, 2, 4
y 8 warps. Las tablas y lo que se deduce de ellas están en [bench-dma.md](../../../32.cpu-gpu-func-sim/docs/bench-dma.md):
la GPU solo gana en `memcpy` y `blit` (1,2 a 1,3 x, desde unos 4 KiB) y pierde siempre en
`memset` y `fill_rect`. Cada transacción de 16 B cuesta unos 38 ciclos de GPU (30 en
`memcpy`), el doble de lo que suponía el simulador de ciclos, y no es por el sondeo de la
CPU: `poll_exp.asm` en la placa lo descarta midiendo con los contadores de la propia GPU.

| Programa | Qué es |
|---|---|
| [harness](harness/dma.asm) | El arnés mínimo del diseño: `memset` y `memcpy` por polling, un job que falla, uno que no termina y la recuperación |
| [rect](rect/rect.asm) | `fill_rect` y `blit` con geometrías incómodas |
| [memset](memset/) | El primer programa en C con CPU y GPU en el mismo fichero |
| [bench-dma](bench-dma/) | Los cuatro kernels, 20 configuraciones, con el resultado comprobado; en la placa, los ciclos |
| [lat-exp](lat-exp/) | ¿Cuánto tarda UNA transacción de la GPU? |
| [poll-exp](poll-exp/) | ¿El sondeo de la CPU frena a la GPU? |

Compartido por los programas de esta carpeta: `gpu_kernels.inc` (los kernels en ensamblador), `gpu_kernels.c`
(los mismos en C; [compare](../../../32.cpu-gpu-func-sim/compare/README.md) los compara) y `poll_exp_perf.inc` (los
contadores de rendimiento de la GPU, con `BOARD`).
