; ============================================================
; bench_dma_board.asm - el benchmark de memset, memcpy, fill_rect y blit (placa 36)
;
;   run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim\examples\dma\bench_dma_board.asm
;   python 32.cpu-gpu-func-sim\examples\dma\bench_dma_report.py
;
; Igual que bench_dma.asm salvo dos includes: el runtime que lanza con RUN (la 36 aún
; no tiene WARP_START) y la medida de ciclos con el contador de la CPU.
; ============================================================

.include "mmio.inc"
.include "bench_dma.inc"
.include "gpu_runtime_board.inc"
.include "gpu_kernels.inc"
.include "../race/bench_board.inc"
