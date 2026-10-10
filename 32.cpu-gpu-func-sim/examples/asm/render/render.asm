; ============================================================
; render.asm - un plasma pintado por la GPU, con la CPU llevando el bucle
;
; Reparto del trabajo, el de siempre en CPU + GPU:
;
;   CPU   configura el vídeo (dos framebuffers, SCANOUT), y en cada frame
;         escribe los argumentos del job, lanza 8 warps con `gpu_run` (el
;         runtime de ../dma), espera a que acaben, pide el SWAP y espera a que
;         el hardware lo aplique.
;   GPU   pinta el framebuffer trasero. 64 hilos, uno por fila de celdas: la
;         pantalla es un mosaico de 80 x 60 celdas de 4 x 4 píxeles y el hilo
;         `cy` pinta las 80 celdas de la fila `cy` (los hilos 60..63 sobran).
;
;   python cpu_gpu_sim.py examples\asm\render\render.asm --window
;   mini-dbg --gpu examples\asm\render\render.asm --window
;
; `--window` abre la ventana y ya implica el vídeo. Sin ventana, `--video` (y
; `fb` dentro de mini-dbg) basta para tener los registros de vídeo.
; Con la ventana abierta se ve el plasma moverse. Para depurar: `break
; gpu_k_render` y `run` paran al lanzar cada frame, `watch` sobre FB_BACK
; enseña quién pinta qué, y `break present` para justo antes del SWAP.
;
; ---- El color de una celda (cx, cy) en el frame t ----
;
; Tres fases de onda triangular, una por canal, con direcciones distintas:
;
;     pa = (cx + cy + t)       & 63      -> R, 5 bits
;     pb = (2*cx - cy + 2*t)   & 63      -> G, 6 bits (la onda 0..31, por 2)
;     pc = (2*cy - cx + 3*t)   & 63      -> B, 5 bits
;
;     tri(p) = |p - 32| con el 32 llevado a 31, es decir 0..31
;
; Sin ramas: |d| = (d xor m) - m con m = d >> 31 aritmético. Así los 8 hilos de
; un warp ejecutan exactamente las mismas instrucciones en el bucle de píxeles
; y solo divergen al principio (los 4 hilos que sobran).
;
; RGB565, 320 x 240, dos píxeles por palabra: la celda de 4 x 4 son 2 palabras
; por línea durante 4 líneas (una línea son 640 bytes).
; ============================================================

; En la placa 36, `run-board` ensambla con -D BOARD: runtime con RUN (la 36 no tiene WARP_START)
; y la medicion de ciclos de CPU de abajo (las lineas entre .ifdef BOARD y .endif).

; ---- SOLO PLACA: mide los ciclos de CPU que tarda en pintarse cada frame ----
; Con la CPU parada (monitor.py halt): R21 = frames, R22 = ciclos acumulados de
; pintado (sin contar la espera al swap), R24 = base del PERF de la CPU.
; R29 = ciclos del frame entero (pintado + espera al swap), R19 = frames validos.
; Los frames que cruzan una parada del monitor (> 200 ms) no se acumulan.
; Media por frame = (R22b - R22a) / (R19b - R19a); a 80 MHz, 80000 ciclos = 1 ms.

.include "mmio.inc"

.equ FB_A,    0x01000000
.equ FB_B,    0x01025800            ; FB_A + 320*240*2
.equ NWARPS,  8
.equ CELLS_X, 80
.equ CELLS_Y, 60

; ---- CPU ----
; R20 = base de VIDEO, R21 = número de frame. gpu_run destruye R1..R15 y R31.
start:
    LI    R20, MMIO_VIDEO_BASE
    LI    R30, FB_A
    STORE R30, R20, MMIO_VIDEO_FB_FRONT_OFF
    LI    R30, FB_B
    STORE R30, R20, MMIO_VIDEO_FB_BACK_OFF
    MOVI  R30, MMIO_VIDEO_MODE_SCANOUT
    STORE R30, R20, MMIO_VIDEO_CTRL_OFF

    ; Un frame son decenas de miles de instrucciones de warp: el límite de
    ; sondeos por defecto del runtime se queda corto si se sube --cpu-steps.
.ifdef BOARD
    ; La placa conserva el estado de la GPU entre ejecuciones: RESET antes del primer job.
    LI    R4, MMIO_GPU_BASE
    MOVI  R5, GPU_CTRL_RESET
    STORE R5, R4, MMIO_GPU_CONTROL_OFF

.endif
    LI    R4, gpu_timeout_polls
    LI    R5, 1000000
    STORE R5, R4, 0

    MOVI  R21, 0
.ifdef BOARD
    MOVI  R22, 0
    MOVI  R29, 0
    MOVI  R19, 0
    LI    R30, 16000000                     ; 200 ms: mas que cualquier frame
    LI    R24, MMIO_CPU_PERF_BASE
.endif

frame:
.ifdef BOARD
    LOAD  R23, R24, MMIO_PERF_CYCLES_OFF    ; inicio del pintado
.endif
    LI    R3, job_args
    LOAD  R4, R20, MMIO_VIDEO_FB_BACK_OFF   ; cambia en cada swap
    STORE R4, R3, 8                         ; p0 = framebuffer donde pintar
    STORE R21, R3, 12                       ; p1 = frame
    LI    R1, gpu_k_render
    MOVI  R2, NWARPS
    JAL   R31, gpu_run
    BNE   R1, R0, failed                    ; GPU_OK = 0

.ifdef BOARD
    LOAD  R28, R24, MMIO_PERF_CYCLES_OFF    ; fin del pintado
    SUB   R18, R28, R23                     ; ciclos de pintado de este frame
.endif
present:
    MOVI  R7, 1
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF      ; pedir el intercambio
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF      ; se aplica al empezar un frame
    BNE   R8, R0, wait_swap
.ifdef BOARD
    LOAD  R28, R24, MMIO_PERF_CYCLES_OFF    ; fin del frame entero (tras el swap)
    SUB   R28, R28, R23
    BGEU  R28, R30, skip_acc                ; cruzo una parada del monitor: no vale
    ADD   R29, R29, R28                     ; R29 = ciclos de frame entero
    ADD   R22, R22, R18                     ; R22 = ciclos de pintado
    ADDI  R19, R19, 1                       ; R19 = frames validos
skip_acc:
.endif
    ADDI  R21, R21, 1
    BRA   frame

failed:
    HALT

; ---- GPU ----
; Argumentos (GETARG): +4 nlanes, +8 p0 = framebuffer, +12 p1 = frame.
;
;   R5 cy (= lwarp*nlanes + lane)   R6 framebuffer      R7 t
;   R8 ya   R9 yb   R10 yc          partes de las fases que no dependen de cx
;   R11 cx  R12 puntero a la celda  R13..R15 las fases, luego R, G, B
;   R16 temporal                    R17 el píxel, luego la palabra
;   R20 = 31  R21 = 5  R22 = 11  R23 = 6  R24 = 16  R25 = 60  R26 = 80
gpu_k_render:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 4                      ; nlanes
    MUL      R5, R2, R4
    ADD      R5, R5, R3                     ; cy
    LOAD     R6, R1, 8                      ; framebuffer
    LOAD     R7, R1, 12                     ; t

    MOVI     R20, 31
    MOVI     R21, 5
    MOVI     R22, 11
    MOVI     R23, 6
    MOVI     R24, 16
    MOVI     R25, CELLS_Y
    MOVI     R26, CELLS_X

    ; Los hilos sin fila que pintar saltan al final: es una divergencia, así
    ; que el SSY va delante y apunta a la salida (como en gpu_kernels.inc).
    SSY      render_end
    BGEU     R5, R25, render_end

    ; lo que no depende de cx
    ADD      R8, R5, R7                     ; ya = cy + t
    ADD      R16, R7, R7                    ; 2t
    SUB      R9, R16, R5                    ; yb = 2t - cy
    ADD      R10, R5, R5
    ADD      R10, R10, R16
    ADD      R10, R10, R7                   ; yc = 2cy + 3t
    MOVI     R16, 2560                      ; 4 líneas de 640 bytes
    MUL      R12, R5, R16
    ADD      R12, R12, R6                   ; puntero a la primera celda de la fila
    MOVI     R11, 0                         ; cx

render_cell:
    ADD      R13, R11, R8                   ; pa = cx + ya
    ADD      R14, R11, R11
    ADD      R14, R14, R9                   ; pb = 2cx + yb
    SUB      R15, R10, R11                  ; pc = yc - cx
    ANDI     R13, R13, 63
    ANDI     R14, R14, 63
    ANDI     R15, R15, 63

    ; tri(p) para las tres fases, sin ramas
    ADDI     R13, R13, -32
    SAR      R16, R13, R20
    XOR      R13, R13, R16
    SUB      R13, R13, R16
    SHR      R16, R13, R21
    SUB      R13, R13, R16

    ADDI     R14, R14, -32
    SAR      R16, R14, R20
    XOR      R14, R14, R16
    SUB      R14, R14, R16
    SHR      R16, R14, R21
    SUB      R14, R14, R16

    ADDI     R15, R15, -32
    SAR      R16, R15, R20
    XOR      R15, R15, R16
    SUB      R15, R15, R16
    SHR      R16, R15, R21
    SUB      R15, R15, R16

    ; RGB565: R en 15:11, G en 10:5 (la onda por 2), B en 4:0
    SHL      R13, R13, R22
    SHL      R14, R14, R23                  ; (g << 1) << 5
    OR       R17, R13, R14
    OR       R17, R17, R15
    SHL      R16, R17, R24
    OR       R17, R17, R16                  ; el mismo píxel dos veces: una palabra

    STORE    R17, R12, 0
    STORE    R17, R12, 4
    STORE    R17, R12, 640
    STORE    R17, R12, 644
    STORE    R17, R12, 1280
    STORE    R17, R12, 1284
    STORE    R17, R12, 1920
    STORE    R17, R12, 1924

    ADDI     R12, R12, 8
    ADDI     R11, R11, 1
    BLT      R11, R26, render_cell
render_end:
    EXIT

; ---- el runtime de CPU (detrás de su HALT: no hay linker) ----
.include "gpu_runtime.inc"

; ---- datos ----
job_args:
    .space 32
