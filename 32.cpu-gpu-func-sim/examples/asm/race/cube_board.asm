; ============================================================
; cube_board.asm - un cubo sólido con texturas, una carrera entre la CPU y la GPU
;                  (placa 36)
;
;   run-board --prototype 36 --program 32.cpu-gpu-func-sim\examples\asm\race\cube_board.asm
;
; Igual que cube.asm salvo dos includes: el runtime que lanza con RUN (la 36 aún no
; tiene WARP_START) y la medida de ciclos con el contador de la CPU.
; ============================================================

.include "mmio.inc"
.include "race_host.inc"
.include "cube.inc"
.include "../dma/gpu_runtime_board.inc"
.include "bench_board.inc"
