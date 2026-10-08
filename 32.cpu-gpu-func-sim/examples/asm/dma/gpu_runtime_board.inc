; ============================================================
; SOLO PARA LA PLACA 36 con el RTL del hito 1. Igual que gpu_runtime.inc salvo
; que lanza con RUN en vez de WARP_START (que en la 36 da error). Diferencias:
;   - RUN reanuda lo que dejan los descriptores: el runtime los reescribe todos los
;     de este job, y un warp ya terminado no esta vivo, asi que no se relanza.
;   - RESET en la 36 tambien borra los descriptores (el contrato dice que no).
; Cuando llegue el hito 2, este fichero sobra: usar gpu_runtime.inc.
; ============================================================
; gpu_runtime_board.inc - gpu_runtime.inc para la 36 en placa (hito 1 del RTL)
;
; Es el runtime minimo de docs/diseno-gpu-dma.md (§4 a §6): un solo job en
; vuelo, por polling, sin interrupciones. Un job son `nwarps` warps que corren
; el mismo kernel sobre un bloque de argumentos compartido.
;
; Se incluye en la imagen de la CPU, detras de su `HALT`: no hay linker, las
; etiquetas son globales y por eso todas empiezan por `gpu_`.
;
; ---- gpu_run ----------------------------------------------------------------
;
;   entrada   R1  PC del kernel (una etiqueta)
;             R2  nwarps (1 .. NUM_WARPS de GPU_CAPS)
;             R3  direccion del bloque de argumentos; el llamador rellena los
;                 parametros p[0..5] (+8 .. +28), gpu_run pone nwarps y nlanes
;   llamada   JAL R31, gpu_run
;   salida    R1  estado: GPU_OK, GPU_ERR_FAULT, GPU_ERR_TIMEOUT, GPU_ERR_ARGS
;                 o GPU_ERR_STATE
;             R2  FIRST_ERROR     (solo con GPU_ERR_FAULT, si no 0)
;             R3  FIRST_ERROR_PC  (idem)
;   destruye  R1 .. R15 y R31. El resto de registros no se toca.
;
; Bloque de argumentos (32 bytes, alineado a 4):
;
;   +0 nwarps   +4 nlanes   +8 p0   +12 p1   +16 p2   +20 p3   +24 p4   +28 p5
;
; Orden de §18 y §5.1: la CPU escribe los datos y los descriptores, y solo
; entonces WARP_START. Nunca RUN: arrancaria tambien los descriptores viejos.
; Orden de §5.2: leer WARP_DONE, limpiar con W1C EXACTAMENTE lo leido, y solo
; entonces mirar si el job ha terminado. Tras un error, WARP_DONE se lee antes
; de RESET (§6), que conserva los descriptores y los arrays de configuracion.
; ============================================================

; GPU_STATUS (mmio.md §14.1)
.equ GPU_ST_IDLE,  0x00000004
.equ GPU_ST_ERROR, 0x00000008

; GPU_CONTROL (mmio.md §14.1): son comandos, de uno en uno
.equ GPU_CTRL_RUN,   0x00000001
.equ GPU_CTRL_HALT,  0x00000002
.equ GPU_CTRL_RESET, 0x00000010

; Estados que devuelve gpu_run
.equ GPU_OK,          0
.equ GPU_ERR_FAULT,   1
.equ GPU_ERR_TIMEOUT, 2
.equ GPU_ERR_ARGS,    3
.equ GPU_ERR_STATE,   4

.equ GPU_TIMEOUT_POLLS, 20000

gpu_run:
    LI    R10, MMIO_GPU_BASE
    LI    R11, MMIO_GPU_WARPS_BASE

    ; ---- validar: nunca se llega a la GPU con argumentos que no caben ----
    LOAD  R4, R10, MMIO_GPU_CAPS_OFF
    ANDI  R5, R4, 0xFF                      ; NUM_WARPS
    SHRI  R6, R4, 8
    ANDI  R6, R6, 0xFF                      ; NUM_LANES
    BEQ   R2, R0, gpu_run_args              ; ni un warp
    BLTU  R5, R2, gpu_run_args              ; mas de los que hay

    ; ---- la GPU tiene que estar libre y sin error (§5.1) ----
    LOAD  R4, R10, MMIO_GPU_STATUS_OFF
    ANDI  R7, R4, GPU_ST_ERROR
    BNE   R7, R0, gpu_run_state
    ANDI  R7, R4, GPU_ST_IDLE
    BEQ   R7, R0, gpu_run_state

    ; ---- bloque de argumentos ----
    STORE R2, R3, 0                         ; nwarps
    STORE R6, R3, 4                         ; nlanes

    MOVI  R7, 1
    SHL   R7, R7, R2
    ADDI  R7, R7, -1                        ; R7 = warps del job = pendientes
    MOVI  R8, 1
    SHL   R8, R8, R6
    ADDI  R8, R8, -1                        ; R8 = ACTIVE: todas las lanes

    ; id de job: el WORKGROUP_ID de sus warps, para que un BAR no mezcle jobs
    LI    R14, gpu_job_seq
    LOAD  R15, R14, 0
    ADDI  R15, R15, 1
    STORE R15, R14, 0

    ; ---- un descriptor por warp logico w = 0 .. nwarps-1, en el slot w ----
    MOVI  R9, 0                             ; w
    MOVI  R12, 0                            ; 16 * w: descriptor
    MOVI  R13, 0                            ;  4 * w: arrays por warp
gpu_run_desc:
    ADD   R14, R11, R12
    STORE R1, R14, MMIO_GPU_WARPS_PC_OFF
    STORE R8, R14, MMIO_GPU_WARPS_ACTIVE_OFF
    STORE R15, R14, MMIO_GPU_WARPS_GROUP_OFF
    ADD   R14, R11, R13
    STORE R9, R14, MMIO_GPU_WARPS_LOGICAL_ID_OFF
    STORE R3, R14, MMIO_GPU_WARPS_ARG_OFF
    ADDI  R9, R9, 1
    ADDI  R12, R12, MMIO_GPU_WARPS_STRIDE
    ADDI  R13, R13, 4
    BLTU  R9, R2, gpu_run_desc

    MOVI  R14, GPU_CTRL_RUN                 ; hito 1: no hay WARP_START, se lanza con RUN
    STORE R14, R10, MMIO_GPU_CONTROL_OFF

    ; ---- esperar (§5.2). R7 = warps pendientes, R4 = sondeos que quedan ----
    LI    R14, gpu_timeout_polls
    LOAD  R4, R14, 0
gpu_run_poll:
    LOAD  R5, R10, MMIO_GPU_STATUS_OFF
    LOAD  R6, R10, MMIO_GPU_WARP_DONE_OFF
    BEQ   R6, R0, gpu_run_check
    STORE R6, R10, MMIO_GPU_WARP_DONE_OFF   ; W1C de exactamente lo leido
    AND   R14, R7, R6
    XOR   R7, R7, R14                       ; pending &= ~done
gpu_run_check:
    ANDI  R14, R5, GPU_ST_ERROR
    BNE   R14, R0, gpu_run_fault
    BEQ   R7, R0, gpu_run_ok
    ADDI  R4, R4, -1
    BNE   R4, R0, gpu_run_poll

    ; ---- el kernel no termina: HALT, y despues RESET (§6) ----
    MOVI  R14, GPU_CTRL_HALT
    STORE R14, R10, MMIO_GPU_CONTROL_OFF
    LOAD  R6, R10, MMIO_GPU_WARP_DONE_OFF   ; lo ultimo que haya, antes de RESET
    STORE R6, R10, MMIO_GPU_WARP_DONE_OFF
    MOVI  R14, GPU_CTRL_RESET
    STORE R14, R10, MMIO_GPU_CONTROL_OFF
    MOVI  R1, GPU_ERR_TIMEOUT
    BRA   gpu_run_end

gpu_run_fault:
    ; GPU_STATUS.ERROR: los warps que no acaban nunca ponen su bit, asi que
    ; esperar mas no serviria. Diagnostico, WARP_DONE y solo entonces RESET.
    LI    R11, MMIO_GPU_SIMT_BASE
    LOAD  R2, R11, MMIO_GPU_SIMT_FIRST_ERROR_OFF
    LOAD  R3, R11, MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF
    LOAD  R6, R10, MMIO_GPU_WARP_DONE_OFF
    STORE R6, R10, MMIO_GPU_WARP_DONE_OFF
    MOVI  R14, GPU_CTRL_RESET
    STORE R14, R10, MMIO_GPU_CONTROL_OFF
    MOVI  R1, GPU_ERR_FAULT
    RET

gpu_run_ok:
    MOVI  R1, GPU_OK
    BRA   gpu_run_end
gpu_run_args:
    MOVI  R1, GPU_ERR_ARGS
    BRA   gpu_run_end
gpu_run_state:
    MOVI  R1, GPU_ERR_STATE
gpu_run_end:
    MOVI  R2, 0
    MOVI  R3, 0
    RET

; ---- estado del runtime (RAM compartida) ----
gpu_job_seq:
    .word 0
gpu_timeout_polls:
    .word GPU_TIMEOUT_POLLS
