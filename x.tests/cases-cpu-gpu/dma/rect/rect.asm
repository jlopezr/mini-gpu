; ============================================================
; rect.asm - fill_rect y blit de la GPU, con geometrías incómodas
;
;   python cpu_gpu_sim.py x.tests\cases-cpu-gpu\dma\rect\rect.asm
;
; Cuatro jobs, de uno en uno; el estado de cada uno queda en RESULTS[n]. Lo que
; escriben en memoria lo comprueba RectKernelsTest (test_cpu_gpu_sim.py), que
; prepara las zonas antes de arrancar con una guarda alrededor de cada rectángulo:
;
;   1. fill_rect, 3 warps, 7 filas de 13 palabras, pitch 96   RESULTS[0]  GPU_OK
;      13 no es múltiplo de 8 lanes y 7 no lo es de 3 warps: la última pasada de
;      cada fila es parcial y las lanes divergen
;   2. blit, 5 warps, 7 filas de 13 palabras, pitch 112 <- 60 RESULTS[1]  GPU_OK
;   3. fill_rect, 1 warp, una sola palabra                    RESULTS[2]  GPU_OK
;   4. blit, 8 warps, 3 filas de 8 palabras: sobran 5 warps   RESULTS[3]  GPU_OK
; ============================================================

.include "mmio.inc"

.equ RESULTS,   0x00010000
.equ RECT_1,    0x00020000
.equ BLIT_SRC1, 0x00030000
.equ BLIT_DST1, 0x00040000
.equ RECT_2,    0x00050000
.equ BLIT_SRC2, 0x00060000
.equ BLIT_DST2, 0x00070000
.equ VALUE_1,   0xAAAA5555
.equ VALUE_2,   0x12345678

start:
    LI    R20, RESULTS

    ; ---- 1. fill_rect ----
    LI    R3, job_args
    LI    R4, RECT_1
    STORE R4, R3, 8                         ; dst
    MOVI  R4, 96
    STORE R4, R3, 12                        ; pitch
    MOVI  R4, 13
    STORE R4, R3, 16                        ; row_words
    MOVI  R4, 7
    STORE R4, R3, 20                        ; rows
    LI    R4, VALUE_1
    STORE R4, R3, 24                        ; valor
    LI    R1, gpu_k_fill_rect
    MOVI  R2, 3
    JAL   R31, gpu_run
    STORE R1, R20, 0

    ; ---- 2. blit ----
    LI    R3, job_args
    LI    R4, BLIT_DST1
    STORE R4, R3, 8                         ; dst
    MOVI  R4, 112
    STORE R4, R3, 12                        ; dst_pitch
    LI    R4, BLIT_SRC1
    STORE R4, R3, 16                        ; src
    MOVI  R4, 60
    STORE R4, R3, 20                        ; src_pitch
    MOVI  R4, 13
    STORE R4, R3, 24                        ; row_words
    MOVI  R4, 7
    STORE R4, R3, 28                        ; rows
    LI    R1, gpu_k_blit
    MOVI  R2, 5
    JAL   R31, gpu_run
    STORE R1, R20, 4

    ; ---- 3. fill_rect de una palabra ----
    LI    R3, job_args
    LI    R4, RECT_2
    STORE R4, R3, 8
    MOVI  R4, 64
    STORE R4, R3, 12
    MOVI  R4, 1
    STORE R4, R3, 16
    STORE R4, R3, 20
    LI    R4, VALUE_2
    STORE R4, R3, 24
    LI    R1, gpu_k_fill_rect
    MOVI  R2, 1
    JAL   R31, gpu_run
    STORE R1, R20, 8

    ; ---- 4. blit con menos filas que warps ----
    LI    R3, job_args
    LI    R4, BLIT_DST2
    STORE R4, R3, 8
    MOVI  R4, 64
    STORE R4, R3, 12
    LI    R4, BLIT_SRC2
    STORE R4, R3, 16
    MOVI  R4, 32
    STORE R4, R3, 20
    MOVI  R4, 8
    STORE R4, R3, 24
    MOVI  R4, 3
    STORE R4, R3, 28
    LI    R1, gpu_k_blit
    MOVI  R2, 8
    JAL   R31, gpu_run
    STORE R1, R20, 12
    HALT

.include "gpu_runtime.inc"
.include "../gpu_kernels.inc"

job_args:
    .space 32
