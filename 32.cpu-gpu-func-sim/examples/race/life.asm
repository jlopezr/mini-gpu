; ============================================================
; life.asm - el juego de la vida, una carrera entre la CPU y la GPU (simulador)
;
;   mini-dbg --gpu examples\race\life.asm --window
;
; El trabajo es siempre el mismo y lo hacen tres métodos que se turnan cada 60
; fotogramas: la CPU sola, la GPU "ingenua" y la GPU "bien puesta". Mira
; race_host.inc para el anfitrión y life.inc para la rejilla y los tres métodos.
; Para la placa, life_board.asm.
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "life.inc"
.include "../dma/gpu_runtime.inc"
.include "bench_sim.inc"
