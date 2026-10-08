; ============================================================
; launch_start.asm - la CPU arranca warps de la GPU de uno en uno con WARP_START
;
; Comprueba las reglas de lanzamiento de mmio.md §14.1 que launch-run no toca:
;
;   * WARP_START arranca SOLO los warps pedidos, aunque haya otros configurados
;     (el warp 0 esta configurado y no corre hasta que se pide);
;   * en reposo, WARP_START pone la GPU en marcha sin RUN;
;   * WARP_DONE es pegajoso por warp: arrancar el warp 0 no borra el bit del 1;
;   * el descriptor no se consume al ejecutar, y GPU_CONTROL.RESET lo conserva
;     (y deja WARP_DONE a cero).
;
; El kernel escribe out[tid] = tid*tid + 1 con tid = warp*8 + lane.
;
; Registros al terminar:
;   R1 = out[8]  = 65     tras arrancar solo el warp 1
;   R2 = out[0]  = 0      el warp 0 aun no ha corrido
;   R3 = out[0]  = 1      tras arrancar el warp 0
;   R4 = ACTIVE del warp 0 tras ejecutar = 0xFF
;   R5 = WARP_DONE tras RESET = 0
;   R6 = ACTIVE del warp 0 tras RESET    = 0xFF
; ============================================================

.include "mmio.inc"

start:
    LI    R10, MMIO_GPU_BASE
    LI    R11, MMIO_GPU_WARPS_BASE
    LI    R12, kernel
    MOVI  R13, 0xFF

    MOVI  R16, 16                           ; GPU_CONTROL.RESET
    STORE R16, R10, MMIO_GPU_CONTROL_OFF
    MOVI  R17, 64
settle:
    ADDI  R17, R17, -1
    BNE   R17, R0, settle

    ; Apagar los warps 2 a 7 (RESET conserva descriptores de ejecuciones previas).
    MOVI  R18, 6
    ADDI  R19, R11, 32 + MMIO_GPU_WARPS_ACTIVE_OFF
off:
    STORE R0, R19, 0
    ADDI  R19, R19, 16
    ADDI  R18, R18, -1
    BNE   R18, R0, off

    ; Los warps 0 y 1 configurados con el mismo kernel.
    STORE R12, R11, MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, MMIO_GPU_WARPS_ACTIVE_OFF
    STORE R12, R11, 16 + MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, 16 + MMIO_GPU_WARPS_ACTIVE_OFF

    ; Arrancar solo el warp 1.
    MOVI  R14, 2
    STORE R14, R10, MMIO_GPU_WARP_START_OFF
wait1:
    LOAD  R15, R10, MMIO_GPU_WARP_DONE_OFF
    BNE   R15, R14, wait1                   ; WARP_DONE == 2: solo el warp 1

    LI    R20, out
    LOAD  R1, R20, 32                       ; out[8]  = 65
    LOAD  R2, R20, 0                        ; out[0]  = 0

    ; Ahora el warp 0. El bit del warp 1 sigue en WARP_DONE.
    MOVI  R21, 1
    STORE R21, R10, MMIO_GPU_WARP_START_OFF
    MOVI  R22, 3
wait2:
    LOAD  R15, R10, MMIO_GPU_WARP_DONE_OFF
    BNE   R15, R22, wait2                   ; WARP_DONE == 3

    LOAD  R3, R20, 0                        ; out[0]  = 1
    LOAD  R4, R11, MMIO_GPU_WARPS_ACTIVE_OFF

    ; RESET: descarta WARP_DONE y conserva el descriptor.
    STORE R16, R10, MMIO_GPU_CONTROL_OFF
    MOVI  R17, 64
settle2:
    ADDI  R17, R17, -1
    BNE   R17, R0, settle2
    LOAD  R5, R10, MMIO_GPU_WARP_DONE_OFF
    LOAD  R6, R11, MMIO_GPU_WARPS_ACTIVE_OFF
    HALT

; ---- GPU: out[tid] = tid*tid + 1 ----
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

; ---- datos: 16 palabras, lo ultimo de la imagen ----
out:
    .word 0, 0, 0, 0, 0, 0, 0, 0
    .word 0, 0, 0, 0, 0, 0, 0, 0
