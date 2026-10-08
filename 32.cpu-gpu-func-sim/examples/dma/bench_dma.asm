; ============================================================
; bench_dma.asm - el benchmark de memset, memcpy, fill_rect y blit (simulador)
;
;   python cpu_gpu_sim.py examples\dma\bench_dma.asm
;
; En el simulador no hay ciclos (bench_sim.inc devuelve cero) y 1 MiB con los 20
; trabajos por operación tarda lo suyo: sirve para comprobar que las 20
; configuraciones dan el resultado correcto (bench_errors a cero). Los ciclos
; salen en la placa: bench_dma_board.asm y bench_dma_report.py. Mira bench_dma.inc.
; ============================================================

.include "mmio.inc"
.include "bench_dma.inc"
.include "gpu_runtime.inc"
.include "gpu_kernels.inc"
.include "../race/bench_sim.inc"
