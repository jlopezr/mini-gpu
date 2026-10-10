; ============================================================
; rotate.asm - una textura girando y acercándose, una carrera entre la CPU y la
;              GPU
;
;   mini-dbg --gpu x.tests\cases-cpu-gpu\race\rotate\rotate.asm --window
;
; Un tablero de colores que da vueltas y se acerca y se aleja. Cada celda de la
; pantalla busca su texel (un gather) y lo copia. El trabajo lo hacen tres métodos
; que se turnan cada 60 fotogramas: la CPU sola, la GPU "ingenua" y la GPU "bien
; puesta". Mira race_host.inc para el anfitrión y rotate.inc para el cálculo.
; En la placa 36 (run-board define BOARD: runtime con RUN y medida con el contador de la CPU):
;   run-board --prototype 36 --program x.tests\cases-cpu-gpu\race\rotate\rotate.asm
; ============================================================

.include "mmio.inc"
.include "../race_host.inc"
.include "rotate.inc"
.include "gpu_runtime.inc"
.include "bench.inc"
