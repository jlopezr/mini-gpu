; ============================================================
; lat_exp_board.asm - ¿cuánto tarda UNA transacción de la GPU? (placa 36)
;
;   run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim\examples\dma\lat_exp_board.asm
;   python 32.cpu-gpu-func-sim\examples\dma\lat_exp_report.py
;
; Mira lat_exp.inc.
; ============================================================

.include "mmio.inc"
.include "lat_exp.inc"
.include "gpu_runtime_board.inc"
.include "poll_exp_perf_board.inc"
.include "../race/bench_board.inc"
