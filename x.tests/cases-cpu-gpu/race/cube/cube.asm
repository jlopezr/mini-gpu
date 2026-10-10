; ============================================================
; cube.asm - un cubo sólido con texturas, una carrera entre la CPU y la GPU
;
;   mini-dbg --gpu x.tests\cases-cpu-gpu\race\cube\cube.asm --window
;
; Un cubo con una textura distinta en cada cara, que gira sobre dos ejes. Los
; píxeles los pintan tres métodos que se turnan cada 60 fotogramas: la CPU sola, la
; GPU "ingenua" y la GPU "bien puesta". Mira race_host.inc para el anfitrión y
; cube.inc para la geometría y los tres métodos.
; En la placa 36 (run-board define BOARD: runtime con RUN y medida con el contador de la CPU):
;   run-board --prototype 36 --program x.tests\cases-cpu-gpu\race\cube\cube.asm
; ============================================================

.include "mmio.inc"
.include "../race_host.inc"
.include "cube.inc"
.include "gpu_runtime.inc"
.include "bench.inc"
