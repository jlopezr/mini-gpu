; ============================================================
; rotate_board.asm - una textura girando, una carrera entre la CPU y la GPU (placa 36)
;
;   run-board --prototype 36 --program 32.cpu-gpu-func-sim\examples\race\rotate_board.asm
;
; Igual que rotate.asm salvo dos includes: el runtime que lanza con RUN (la 36 aún
; no tiene WARP_START) y la medida de ciclos con el contador de la CPU.
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "rotate.inc"
.include "../dma/gpu_runtime_board.inc"
.include "bench_board.inc"
