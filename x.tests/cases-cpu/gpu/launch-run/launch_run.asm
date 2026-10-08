; ============================================================
; launch_run.asm - la CPU lanza dos warps de la GPU con GPU_CONTROL.RUN
;
; Es examples/launch.asm de 32.cpu-gpu-func-sim con dos cambios:
;
;   * empieza con GPU_CONTROL.RESET y apaga los warps que no usa (ACTIVE = 0), para
;     no heredar WARP_DONE ni descriptores de una ejecucion anterior (la GPU sigue
;     ahi entre un caso y el siguiente). RESET conserva los descriptores desde el
;     hito 2 (mmio.md §14.1), asi que apagarlos hay que hacerlo; en el hito 1 no
;     hacia falta y el programa vale igual;
;   * lanza con RUN en vez de WARP_START. Los warps con ACTIVE = 0 no arrancan.
;     El caso launch-start usa WARP_START.
;
; Un solo fichero: el codigo de la CPU empieza en 0 y el kernel de la GPU va
; detras, en la misma imagen. El kernel escribe out[tid] = tid*tid + 1 con
; tid = warp*8 + lane, o sea 16 palabras para los warps 0 y 1.
;
; Registros al terminar:
;   R1 = out[1]  = 2            R2 = out[15] = 226
; ============================================================

.include "mmio.inc"

start:
    LI    R10, MMIO_GPU_BASE
    LI    R11, MMIO_GPU_WARPS_BASE
    LI    R12, kernel
    MOVI  R13, 0xFF

    MOVI  R16, 16                           ; GPU_CONTROL.RESET
    STORE R16, R10, MMIO_GPU_CONTROL_OFF

    ; Tras RESET la GPU tarda unos ciclos en volver a estar parada (reinicia el
    ; banco de registros); se espera antes de tocar los descriptores.
    MOVI  R17, 64
settle:
    ADDI  R17, R17, -1
    BNE   R17, R0, settle

    ; Apagar los warps 2 a 7: puede que una ejecucion anterior los dejara
    ; habilitados, y RUN arrancaria todos los que tengan ACTIVE != 0.
    MOVI  R18, 6
    ADDI  R19, R11, 32 + MMIO_GPU_WARPS_ACTIVE_OFF
off:
    STORE R0, R19, 0
    ADDI  R19, R19, 16
    ADDI  R18, R18, -1
    BNE   R18, R0, off

    STORE R12, R11, MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, MMIO_GPU_WARPS_ACTIVE_OFF
    STORE R12, R11, 16 + MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, 16 + MMIO_GPU_WARPS_ACTIVE_OFF

    MOVI  R14, 3
    MOVI  R16, 1                            ; GPU_CONTROL.RUN
    STORE R16, R10, MMIO_GPU_CONTROL_OFF

wait:
    LOAD  R15, R10, MMIO_GPU_WARP_DONE_OFF
    BNE   R15, R14, wait

    STORE R14, R10, MMIO_GPU_WARP_DONE_OFF  ; W1C: los dos warps, ya consumidos

    LI    R20, out
    LOAD  R1, R20, 4                        ; out[1]  = 2
    LOAD  R2, R20, 60                       ; out[15] = 226
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
