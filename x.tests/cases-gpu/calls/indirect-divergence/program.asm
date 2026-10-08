; Un JR cuyo destino depende de la lane. Las ocho lanes activas calculan destinos
; distintos (b + 4*lane): no hay un destino que apilar en la pila de divergencia,
; asi que el warp para con ERROR_SIMT (0x06) en lugar de elegir uno.
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
