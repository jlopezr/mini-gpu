; ============================================================
; lat_exp.asm - ¿cuánto tarda UNA transacción de la GPU?
;
;   python cpu_gpu_sim.py examples\asm\dma\lat_exp.asm
;   run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim\examples\asm\dma\lat_exp.asm
;   python 32.cpu-gpu-func-sim\examples\asm\dma\lat_exp_report.py
;
; En el simulador no hay contadores ni ciclos: sirve para comprobar que los 24 trabajos
; terminan y escriben donde deben. La medida está en la placa 36 (run-board define
; BOARD). Mira lat_exp.inc.
; ============================================================

.include "mmio.inc"
.include "lat_exp.inc"
.include "gpu_runtime.inc"
.include "poll_exp_perf.inc"
.include "bench.inc"
