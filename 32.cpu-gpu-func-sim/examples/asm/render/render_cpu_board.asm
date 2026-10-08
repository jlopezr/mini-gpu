; ---- SOLO PLACA: mide los ciclos de CPU que tarda en pintarse cada frame ----
; Con la CPU parada (monitor.py halt): R21 = frames, R22 = ciclos acumulados de
; pintado (sin contar la espera al swap), R24 = base del PERF de la CPU.
; R29 = ciclos del frame entero (pintado + espera al swap), R19 = frames validos.
; Los frames que cruzan una parada del monitor (> 200 ms) no se acumulan.
; Media por frame = (R22b - R22a) / (R19b - R19a); a 80 MHz, 80000 ciclos = 1 ms.
; ============================================================
; render_cpu.asm - el mismo plasma que render.asm, pintado solo por la CPU
;
; Es la referencia contra la que medir lo que aporta la GPU: misma imagen
; byte a byte (el test lo comprueba), misma aritmética, mismo mosaico de
; 80 x 60 celdas de 4 x 4 píxeles y mismo doble buffer. Cambia quién pinta:
; aquí un solo hilo recorre las 4 800 celdas, y sus desplazamientos son los
; inmediatos de la CPU (SARI, SHRI, SHLI) en vez de los de registro de la GPU.
;
;   mini-dbg examples\asm\render\render_cpu.asm --window
;
; El color de una celda (cx, cy) en el frame t es el de render.asm:
;
;     pa = (cx + cy + t)       & 63      -> R, 5 bits
;     pb = (2*cx - cy + 2*t)   & 63      -> G, 6 bits (la onda 0..31, por 2)
;     pc = (2*cy - cx + 3*t)   & 63      -> B, 5 bits
;     tri(p) = |p - 32| con el 32 llevado a 31
;
; Registros:
;   R5 cy   R6 framebuffer   R21 t   R20 base de VIDEO
;   R8 ya   R9 yb   R10 yc   R11 cx  R12 puntero a la celda  R27 fila actual
;   R13..R15 las fases, luego R, G, B   R16 temporal   R17 el píxel / la palabra
;   R25 = 60 (filas)   R26 = 80 (columnas)
; ============================================================

.include "mmio.inc"

.equ FB_A,    0x01000000
.equ FB_B,    0x01025800            ; FB_A + 320*240*2
.equ CELLS_X, 80
.equ CELLS_Y, 60

start:
    LI    R20, MMIO_VIDEO_BASE
    LI    R30, FB_A
    STORE R30, R20, MMIO_VIDEO_FB_FRONT_OFF
    LI    R30, FB_B
    STORE R30, R20, MMIO_VIDEO_FB_BACK_OFF
    MOVI  R30, MMIO_VIDEO_MODE_SCANOUT
    STORE R30, R20, MMIO_VIDEO_CTRL_OFF

    MOVI  R25, CELLS_Y
    MOVI  R26, CELLS_X
    MOVI  R21, 0                            ; t
    MOVI  R22, 0
    MOVI  R29, 0
    MOVI  R19, 0
    LI    R30, 16000000                     ; 200 ms: mas que cualquier frame
    LI    R24, MMIO_CPU_PERF_BASE

frame:
    LOAD  R23, R24, MMIO_PERF_CYCLES_OFF    ; inicio del pintado
    LOAD  R6, R20, MMIO_VIDEO_FB_BACK_OFF   ; cambia en cada swap
    ADDI  R27, R6, 0                        ; puntero a la primera celda de la fila
    MOVI  R5, 0                             ; cy

row:
    ; lo que no depende de cx
    ADD   R8, R5, R21                       ; ya = cy + t
    ADD   R16, R21, R21                     ; 2t
    SUB   R9, R16, R5                       ; yb = 2t - cy
    ADD   R10, R5, R5
    ADD   R10, R10, R16
    ADD   R10, R10, R21                     ; yc = 2cy + 3t
    ADDI  R12, R27, 0
    MOVI  R11, 0                            ; cx

cell:
    ADD   R13, R11, R8                      ; pa = cx + ya
    ADD   R14, R11, R11
    ADD   R14, R14, R9                      ; pb = 2cx + yb
    SUB   R15, R10, R11                     ; pc = yc - cx
    ANDI  R13, R13, 63
    ANDI  R14, R14, 63
    ANDI  R15, R15, 63

    ; tri(p) para las tres fases, sin ramas
    ADDI  R13, R13, -32
    SARI  R16, R13, 31
    XOR   R13, R13, R16
    SUB   R13, R13, R16
    SHRI  R16, R13, 5
    SUB   R13, R13, R16

    ADDI  R14, R14, -32
    SARI  R16, R14, 31
    XOR   R14, R14, R16
    SUB   R14, R14, R16
    SHRI  R16, R14, 5
    SUB   R14, R14, R16

    ADDI  R15, R15, -32
    SARI  R16, R15, 31
    XOR   R15, R15, R16
    SUB   R15, R15, R16
    SHRI  R16, R15, 5
    SUB   R15, R15, R16

    ; RGB565: R en 15:11, G en 10:5 (la onda por 2), B en 4:0
    SHLI  R13, R13, 11
    SHLI  R14, R14, 6                       ; (g << 1) << 5
    OR    R17, R13, R14
    OR    R17, R17, R15
    SHLI  R16, R17, 16
    OR    R17, R17, R16                     ; el mismo píxel dos veces: una palabra

    STORE R17, R12, 0
    STORE R17, R12, 4
    STORE R17, R12, 640
    STORE R17, R12, 644
    STORE R17, R12, 1280
    STORE R17, R12, 1284
    STORE R17, R12, 1920
    STORE R17, R12, 1924

    ADDI  R12, R12, 8
    ADDI  R11, R11, 1
    BLT   R11, R26, cell

    ADDI  R27, R27, 2560                    ; la fila siguiente: 4 líneas de 640 bytes
    ADDI  R5, R5, 1
    BLT   R5, R25, row

    LOAD  R28, R24, MMIO_PERF_CYCLES_OFF    ; fin del pintado
    SUB   R18, R28, R23                     ; ciclos de pintado de este frame
present:
    MOVI  R7, 1
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF      ; pedir el intercambio
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF      ; se aplica al empezar un frame
    BNE   R8, R0, wait_swap
    LOAD  R28, R24, MMIO_PERF_CYCLES_OFF    ; fin del frame entero (tras el swap)
    SUB   R28, R28, R23
    BGEU  R28, R30, skip_acc                ; cruzo una parada del monitor: no vale
    ADD   R29, R29, R28                     ; R29 = ciclos de frame entero
    ADD   R22, R22, R18                     ; R22 = ciclos de pintado
    ADDI  R19, R19, 1                       ; R19 = frames validos
skip_acc:
    ADDI  R21, R21, 1
    BRA   frame
