; ============================================================
; bench_dma.asm - el benchmark de memset, memcpy, fill_rect y blit
;
;   python cpu_gpu_sim.py examples\asm\dma\bench_dma.asm
;   run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim\examples\asm\dma\bench_dma.asm
;   python 32.cpu-gpu-func-sim\examples\asm\dma\bench_dma_report.py
;
; En el simulador no hay ciclos (bench.inc devuelve cero sin BOARD) y 1 MiB con los 20
; trabajos por operación tarda lo suyo: sirve para comprobar que las 20
; configuraciones dan el resultado correcto (bench_errors a cero). Los ciclos
; salen en la placa 36 (run-board define BOARD: el runtime que lanza con RUN, porque
; aún no tiene WARP_START, y la medida con el contador de la CPU): bench_dma_report.py.
; Mira bench_dma.inc.
; ============================================================

.include "mmio.inc"
.include "bench_dma.inc"
.include "gpu_runtime.inc"
.include "gpu_kernels.inc"
.include "bench.inc"
