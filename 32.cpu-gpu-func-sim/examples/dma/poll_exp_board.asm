; ============================================================
; poll_exp_board.asm - ¿el sondeo de la CPU frena a la GPU? (placa 36)
;
;   run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim\examples\dma\poll_exp_board.asm
;   python 32.cpu-gpu-func-sim\examples\dma\poll_exp_report.py
;
; Mide con los contadores de rendimiento de la GPU, que no dependen de cómo espere la
; CPU. Mira poll_exp.inc.
; ============================================================

.include "mmio.inc"
.include "poll_exp.inc"
.include "gpu_runtime_board.inc"
.include "gpu_kernels.inc"
.include "poll_exp_perf_board.inc"
.include "../race/bench_board.inc"
