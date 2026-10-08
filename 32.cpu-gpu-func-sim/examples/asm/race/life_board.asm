; ============================================================
; life_board.asm - el juego de la vida, una carrera entre la CPU y la GPU (placa 36)
;
;   run-board --prototype 36 --program 32.cpu-gpu-func-sim\examples\asm\race\life_board.asm
;
; Igual que life.asm salvo dos includes: el runtime que lanza con RUN (la 36 aún no
; tiene WARP_START) y la medida de ciclos con el contador de la CPU, que es lo
; que dibuja la gráfica de tiempos de arriba.
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "life.inc"
.include "../dma/gpu_runtime_board.inc"
.include "bench_board.inc"
