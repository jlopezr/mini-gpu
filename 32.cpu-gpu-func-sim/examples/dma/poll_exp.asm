; ============================================================
; poll_exp.asm - ¿el sondeo de la CPU frena a la GPU? (simulador)
;
;   python cpu_gpu_sim.py examples\dma\poll_exp.asm
;
; En el simulador no hay contadores ni ciclos: sirve para comprobar que los 24
; trabajos dan el resultado correcto. La medida está en poll_exp_board.asm.
; Mira poll_exp.inc.
; ============================================================

.include "mmio.inc"
.include "poll_exp.inc"
.include "gpu_runtime.inc"
.include "gpu_kernels.inc"
.include "poll_exp_perf_sim.inc"
.include "../race/bench_sim.inc"
