; ============================================================
; launch.asm - la CPU lanza dos warps y espera a que acaben
;
; Un solo fichero: el codigo de la CPU empieza en 0 y el kernel de la GPU va
; detras, en la misma imagen y la misma RAM. Ninguna direccion esta escrita a
; mano: la CPU usa las etiquetas `kernel` y `out`. Se ejecuta con
;
;   python cpu_gpu_sim.py examples\launch.asm
;
; El orden es el de mmio.md §18:
;
;   1. la CPU escribe los descriptores de los warps (GPU WARPS)
;   2. la CPU escribe WARP_START
;   3. la GPU ejecuta
;   4. la CPU sondea WARP_DONE hasta ver sus dos bits
;   5. la CPU lo limpia (W1C) y lee los resultados de la RAM compartida
;
; El kernel escribe out[tid] = tid*tid + 1 (tid = warp*8 + lane), asi que con los
; warps 0 y 1 quedan 16 palabras.
;
; Registros de la CPU:
;   R10 base de GPU CORE      R11 base de GPU WARPS     R12 PC del kernel
;   R13 ACTIVE (todas las lanes)   R14 mascara de warps (0b11)
;   R15 WARP_DONE leido       R20 direccion de out
; ============================================================

.include "mmio.inc"

; ---- CPU ----
start:
    LI    R10, MMIO_GPU_BASE
    LI    R11, MMIO_GPU_WARPS_BASE
    LI    R12, kernel
    MOVI  R13, 0xFF

    ; descriptor del warp 0
    STORE R12, R11, MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, MMIO_GPU_WARPS_ACTIVE_OFF
    ; descriptor del warp 1, a MMIO_GPU_WARPS_STRIDE (16) bytes
    STORE R12, R11, 16 + MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, 16 + MMIO_GPU_WARPS_ACTIVE_OFF

    MOVI  R14, 3
    STORE R14, R10, MMIO_GPU_WARP_START_OFF

wait:
    LOAD  R15, R10, MMIO_GPU_WARP_DONE_OFF
    BNE   R15, R14, wait

    STORE R14, R10, MMIO_GPU_WARP_DONE_OFF  ; W1C: los dos warps, ya consumidos

    LI    R20, out
    LOAD  R1, R20, 4                        ; out[1]  = 2
    LOAD  R2, R20, 60                       ; out[15] = 226
    HALT

; ---- GPU: out[tid] = tid*tid + 1 ----
; La GPU no tiene SHLI, asi que el *4 va con un SHL por registro.
kernel:
    GETTID R1
    MUL    R2, R1, R1
    ADDI   R2, R2, 1
    MOVI   R3, 2
    SHL    R4, R1, R3                       ; tid * 4
    LI     R5, out
    ADD    R4, R4, R5
    STORE  R2, R4, 0
    HALT

; ---- datos: 16 palabras, la ultima cosa de la imagen ----
out:
    .word 0, 0, 0, 0, 0, 0, 0, 0
    .word 0, 0, 0, 0, 0, 0, 0, 0
