; ============================================================
; registers.asm - prueba basica de los registros de video
;
; No dibuja pixeles. Comprueba desde la CPU que:
;
;   - FB_FRONT y FB_BACK conservan las direcciones que se escriben;
;   - las direcciones validas estan alineadas a 16 bytes;
;   - SWAP intercambia FRONT y BACK;
;   - STATUS permite leer UNDERFLOW.
;
; El programa espera a que SWAP deje de estar pendiente antes de comprobar las
; bases. Asi no depende del instante del frame en que se hizo la peticion.
;
; Registros:
;   R1/R2   FRONT/BACK antes del swap
;   R3/R4   FRONT/BACK despues del swap
;   R5      lectura de prueba de FB_BACK
;   R6      UNDERFLOW
;   R8      estado de SWAP durante la espera
;   R20     base MMIO de VIDEO
; ============================================================

.include "mmio.inc"

start:
    LI    R20, MMIO_VIDEO_BASE

    ; Usar dos framebuffers conocidos. No dependemos de valores anteriores.
    MOVHI R9, 0x0100
    STORE R9, R20, MMIO_VIDEO_FB_FRONT_OFF
    MOVHI R9, 0x0102
    ORI   R9, R9, 0x5800
    STORE R9, R20, MMIO_VIDEO_FB_BACK_OFF

    ; Leer las bases iniciales para comprobarlas al terminar.
    LOAD  R1, R20, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT
    LOAD  R2, R20, MMIO_VIDEO_FB_BACK_OFF            ; FB_BACK

    ; Probar por separado que FB_BACK conserva exactamente una direccion valida.
    MOVHI R7, 0x0110
    STORE R7, R20, MMIO_VIDEO_FB_BACK_OFF
    LOAD  R5, R20, MMIO_VIDEO_FB_BACK_OFF            ; debe salir 0x01100000

    ; Restaurar el framebuffer trasero y pedir el intercambio.
    STORE R2, R20, MMIO_VIDEO_FB_BACK_OFF
    MOVI  R21, 1
    STORE R21, R20, MMIO_VIDEO_SWAP_OFF          ; SWAP

wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF
    BNE   R8, R0, wait_swap    ; esperar a que el hardware lo aplique

    ; El antiguo BACK debe ser FRONT, y el antiguo FRONT debe ser BACK.
    LOAD  R3, R20, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT, deberia valer el FB_BACK de antes
    LOAD  R4, R20, MMIO_VIDEO_FB_BACK_OFF            ; FB_BACK,  deberia valer el FB_FRONT de antes

    ; Leer y aislar STATUS.UNDERFLOW.
    LOAD  R6, R20, MMIO_VIDEO_STATUS_OFF
    ANDI  R6, R6, 1

    HALT
