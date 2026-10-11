; ============================================================
; race_host.inc - el anfitrión común de los demos "carrera"
;
; Cada demo hace el MISMO trabajo con tres métodos y los va rotando:
;
;     0  la CPU sola
;     1  la GPU "ingenua": un hilo por fila, las 8 lanes de un warp tocan 8 filas
;     2  la GPU "bien puesta": las 8 lanes tocan 8 palabras seguidas
;
; El anfitrión es la CPU y lleva lo que no cambia de un demo a otro: el vídeo con
; doble buffer, el método que toca (cambia cada `race_period` fotogramas), la
; medida de ciclos de cada trabajo y la gráfica de tiempos de arriba del todo.
;
; ---- La gráfica (las 32 primeras líneas del framebuffer) ----
; Una columna por fotograma, avanzando hacia la derecha y dando la vuelta a los
; 320 px. Su altura es el tiempo que tardó el trabajo (ciclos de CPU >> race_shift)
; y su color, el método: verde la CPU, naranja la GPU ingenua, cian la GPU bien
; puesta. En la gráfica se ve el escalón al cambiar de método; en la animación de
; debajo, que ese fotograma tarda más o menos. En el simulador la altura es cero
; (ver bench.inc): los ciclos solo existen en la placa.
;
; ---- Lo que tiene que poner el demo ----
;
;   demo_setup     JAL: deja listo su estado (limpia, siembra...)
;   demo_prepare   JAL: rellena job_args (+8 p0 .. +28 p5) para este fotograma
;   demo_cpu       JAL: hace el trabajo con la CPU, leyendo job_args
;   demo_advance   JAL: pasa al estado siguiente (después del swap)
;   race_kernels   .word 0, <kernel ingenuo>, <kernel bien puesto>
;   race_pixels    .word 3 colores, ya duplicados (dos píxeles RGB565 por palabra)
;   race_cycles    .word 0, 0, 0: el anfitrión guarda aquí los ciclos del último
;                  trabajo de cada método (para leerlos desde el monitor)
;   race_period    .word fotogramas por método
;   race_shift     .word desplazamiento ciclos -> altura de la gráfica
;   job_args       .space 32
;
; ---- Registros ----
; Del anfitrión (el demo no los toca): R17 ciclos al empezar el trabajo,
; R20 base de VIDEO, R21 fotograma, R22 método, R23 cuenta atrás, R24 columna.
; El demo puede usar el resto. Las rutinas JAL vuelven con RET (R31); gpu_run
; destruye R1..R15 y R31, así que ningún valor del anfitrión vive ahí.
; ============================================================

.equ FB_A,    0x01000000
.equ FB_B,    0x01025800            ; FB_A + 320*240*2
.equ NWARPS,  8
.equ STRIP_H, 32                    ; líneas de la gráfica

start:
    LI    R20, MMIO_VIDEO_BASE
    LI    R30, FB_A
    STORE R30, R20, MMIO_VIDEO_FB_FRONT_OFF
    LI    R30, FB_B
    STORE R30, R20, MMIO_VIDEO_FB_BACK_OFF
    MOVI  R30, MMIO_VIDEO_MODE_SCANOUT
    STORE R30, R20, MMIO_VIDEO_CTRL_OFF

    ; La placa conserva el estado de la GPU entre ejecuciones (el reset de la CPU no
    ; la toca): un RESET deja descriptores y warps limpios antes del primer trabajo.
    LI    R4, MMIO_GPU_BASE
    MOVI  R5, GPU_CTRL_RESET
    STORE R5, R4, MMIO_GPU_CONTROL_OFF

    LI    R4, gpu_timeout_polls
    LI    R5, 1000000
    STORE R5, R4, 0

    ; la gráfica empieza en blanco en los dos buffers (la SDRAM llega sin inicializar)
    LI    R4, FB_A
    LI    R5, FB_B
    MOVI  R6, 0
    LI    R7, 5120                          ; STRIP_H líneas de 160 palabras
race_clear:
    STORE R0, R4, 0
    STORE R0, R5, 0
    ADDI  R4, R4, 4
    ADDI  R5, R5, 4
    ADDI  R6, R6, 1
    BLT   R6, R7, race_clear

    JAL   R31, bench_init
    JAL   R31, demo_setup

    MOVI  R21, 0
    MOVI  R22, 0
    MOVI  R24, 0
    LI    R4, race_period
    LOAD  R23, R4, 0

frame:
    JAL   R31, demo_prepare
    JAL   R31, bench_now
    ADDI  R17, R1, 0                        ; ciclos al empezar el trabajo
    BEQ   R22, R0, run_cpu

    SHLI  R4, R22, 2
    LI    R5, race_kernels
    ADD   R5, R5, R4
    LOAD  R1, R5, 0                         ; kernel de este método
    MOVI  R2, NWARPS
    LI    R3, job_args
    JAL   R31, gpu_run
    BNE   R1, R0, failed                    ; GPU_OK = 0
    BRA   timed
run_cpu:
    JAL   R31, demo_cpu

timed:
    JAL   R31, bench_now
    SUB   R16, R1, R17                      ; ciclos del trabajo
    SHLI  R4, R22, 2
    LI    R5, race_cycles
    ADD   R5, R5, R4
    STORE R16, R5, 0                        ; el último de cada método, para leerlo desde fuera
    JAL   R31, race_strip

present:
    MOVI  R7, 1
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF      ; pedir el intercambio
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF      ; se aplica al empezar un frame de vídeo
    BNE   R8, R0, wait_swap

    JAL   R31, demo_advance
    ADDI  R21, R21, 1

    ; ¿toca cambiar de método?
    ADDI  R23, R23, -1
    BNE   R23, R0, frame
    LI    R4, race_period
    LOAD  R23, R4, 0
    ADDI  R22, R22, 1
    MOVI  R4, 3
    BLT   R22, R4, frame
    MOVI  R22, 0
    BRA   frame

failed:
    HALT

; ---- la columna de la gráfica ----
; entrada: R16 = ciclos del trabajo, R22 = método, R24 = columna (0..319)
race_strip:
    LI    R3, race_shift
    LOAD  R3, R3, 0
    SHR   R4, R16, R3                       ; altura
    MOVI  R5, STRIP_H
    BLT   R4, R5, strip_h_ok
    ADDI  R4, R5, 0                         ; tope
strip_h_ok:
    SUB   R8, R5, R4                        ; primera línea con color (desde arriba)
    SHLI  R6, R22, 2
    LI    R7, race_pixels
    ADD   R7, R7, R6
    LOAD  R6, R7, 0                         ; color del método (STOREH usa la mitad baja)
    ADD   R9, R24, R24                      ; 2 bytes por píxel
    LI    R10, FB_A
    ADD   R10, R10, R9
    LI    R11, FB_B
    ADD   R11, R11, R9
    MOVI  R12, 0                            ; línea
strip_row:
    MOVI  R13, 0
    BLT   R12, R8, strip_put
    ADDI  R13, R6, 0
strip_put:
    STOREH R13, R10, 0
    STOREH R13, R11, 0
    ADDI  R10, R10, 640
    ADDI  R11, R11, 640
    ADDI  R12, R12, 1
    BLT   R12, R5, strip_row

    ADDI  R24, R24, 1                       ; la columna siguiente
    MOVI  R4, 320
    BLT   R24, R4, strip_done
    MOVI  R24, 0
strip_done:
    RET
