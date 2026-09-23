.include "mmio.inc"

start:
    LI    R2, MMIO_VIDEO_BASE

    ; FRONT = 0x01000000
    MOVHI R20, 0x0100
    STORE R20, R2, MMIO_VIDEO_FB_FRONT_OFF

    ; Copiar RGB565 320x240 a FRONT
    LA    R22, image
    LI    R23, 38400

copy_image:
    LOAD  R27, R22, 0
    STORE R27, R20, 0

    ADDI  R22, R22, 4
    ADDI  R20, R20, 4

    ADDI  R23, R23, -1
    BNE   R23, R0, copy_image

    ; Activar scanout solamente cuando el framebuffer
    ; ya está completamente escrito.
    MOVI  R28, MMIO_VIDEO_MODE_SCANOUT
    STORE R28, R2, MMIO_VIDEO_CTRL_OFF

forever:
    BRA forever

.rodata

image:
    .incbin "minigpu-small.bin"