; Kernel de gpu_jump_tb, fase 2: un JR cuyo destino depende de la lane. Las ocho
; lanes activas calculan destinos distintos, asi que el SM debe parar con
; ERROR_SIMT (0x06) en lugar de elegir uno. El banco lo carga en 0x400.
kernel:
    GETLANE R1
    MOVI    R2, 2
    SHL     R3, R1, R2
    JAL     R5, b
b:
    ADD     R5, R5, R3          ; b + 4*lane
    JR      R5
    HALT
    HALT
    HALT
    HALT
    HALT
    HALT
    HALT
    HALT
