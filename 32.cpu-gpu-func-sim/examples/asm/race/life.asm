; ============================================================
; life.asm - el juego de la vida, una carrera entre la CPU y la GPU
;
;   mini-dbg --gpu examples\asm\race\life.asm --window
;
; El trabajo es siempre el mismo y lo hacen tres métodos que se turnan cada 60
; fotogramas: la CPU sola, la GPU "ingenua" y la GPU "bien puesta". Mira
; race_host.inc para el anfitrión y life.inc para la rejilla y los tres métodos.
; En la placa 36 (run-board define BOARD: runtime con RUN y medida con el contador de la CPU):
;   run-board --prototype 36 --program 32.cpu-gpu-func-sim\examples\asm\race\life.asm
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "life.inc"
.include "gpu_runtime.inc"
.include "bench.inc"
