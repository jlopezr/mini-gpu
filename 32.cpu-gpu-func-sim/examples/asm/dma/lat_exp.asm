; ============================================================
; lat_exp.asm - ¿cuánto tarda UNA transacción de la GPU? (simulador)
;
;   python cpu_gpu_sim.py examples\asm\dma\lat_exp.asm
;
; En el simulador no hay contadores ni ciclos: sirve para comprobar que los 24 trabajos
; terminan y escriben donde deben. La medida está en lat_exp_board.asm. Mira lat_exp.inc.
; ============================================================

.include "mmio.inc"
.include "lat_exp.inc"
.include "gpu_runtime.inc"
.include "poll_exp_perf_sim.inc"
.include "../race/bench_sim.inc"
