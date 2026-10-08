; ============================================================
; blur.asm - difusión de calor, una carrera entre la CPU y la GPU (simulador)
;
;   mini-dbg --gpu examples\race\blur.asm --window
;
; Tres puntos calientes se mueven por la pantalla y un desenfoque 3 x 3 repetido
; los va extendiendo y apagando. El trabajo lo hacen tres métodos que se turnan
; cada 60 fotogramas: la CPU sola, la GPU "ingenua" y la GPU "bien puesta".
; Mira race_host.inc para el anfitrión y blur.inc para el cálculo.
; Para la placa, blur_board.asm.
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "blur.inc"
.include "../dma/gpu_runtime.inc"
.include "bench_sim.inc"
