; ============================================================
; cube.asm - un cubo sólido con texturas, una carrera entre la CPU y la GPU
;            (simulador)
;
;   mini-dbg --gpu examples\race\cube.asm --window
;
; Un cubo con una textura distinta en cada cara, que gira sobre dos ejes. Los
; píxeles los pintan tres métodos que se turnan cada 60 fotogramas: la CPU sola, la
; GPU "ingenua" y la GPU "bien puesta". Mira race_host.inc para el anfitrión y
; cube.inc para la geometría y los tres métodos.
; Para la placa, cube_board.asm.
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "cube.inc"
.include "../dma/gpu_runtime.inc"
.include "bench_sim.inc"
