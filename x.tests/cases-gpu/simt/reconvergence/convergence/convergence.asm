; Divergencia por lane y reconvergencia estructurada.
; lanes 0..3 producen 11; lanes 4..7 producen 21.

start:
    GETTID R1
    MOVI   R2, 4
    SSY    join
    BLT    R1, R2, low
    MOVI   R3, 20
    BRA    join

low:
    MOVI   R3, 10

join:
    ADDI   R3, R3, 1

    ; framebuffer de prueba: 0x200 + lane * 4
    MOVI   R4, 4
    MUL    R5, R1, R4
    MOVI   R6, 0x0200
    ADD    R5, R6, R5
    STORE  R3, R5, 0
    EXIT
