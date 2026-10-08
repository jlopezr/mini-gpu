; ============================================================
; rotate.asm - una textura girando y acercándose, una carrera entre la CPU y la
;              GPU (simulador)
;
;   mini-dbg --gpu examples\race\rotate.asm --window
;
; Un tablero de colores que da vueltas y se acerca y se aleja. Cada celda de la
; pantalla busca su texel (un gather) y lo copia. El trabajo lo hacen tres métodos
; que se turnan cada 60 fotogramas: la CPU sola, la GPU "ingenua" y la GPU "bien
; puesta". Mira race_host.inc para el anfitrión y rotate.inc para el cálculo.
; Para la placa, rotate_board.asm.
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "rotate.inc"
.include "../dma/gpu_runtime.inc"
.include "bench_sim.inc"
