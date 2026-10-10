; ============================================================
; poll_exp.asm - ¿el sondeo de la CPU frena a la GPU?
;
;   python cpu_gpu_sim.py examples\asm\dma\poll_exp.asm
;   run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim\examples\asm\dma\poll_exp.asm
;   python 32.cpu-gpu-func-sim\examples\asm\dma\poll_exp_report.py
;
; En el simulador no hay contadores ni ciclos: sirve para comprobar que los 24
; trabajos dan el resultado correcto. La medida está en la placa 36 (run-board define
; BOARD): mide con los contadores de rendimiento de la GPU, que no dependen de cómo
; espere la CPU. Mira poll_exp.inc.
; ============================================================

.include "mmio.inc"
.include "poll_exp.inc"
.include "gpu_runtime.inc"
.include "gpu_kernels.inc"
.include "poll_exp_perf.inc"
.include "bench.inc"
