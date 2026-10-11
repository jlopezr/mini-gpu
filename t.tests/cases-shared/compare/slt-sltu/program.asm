; SLT y SLTU sobre dieciseis pares de borde; cada resultado va a RAM.
; Un solo hilo activo, asi el programa es el mismo en CPU y GPU.
        LI    R10, 0x1000
        LI    R1, 0x00000001
        LI    R2, 0x00000002
        SLT   R3, R1, R2
        STORE R3, R10, 0
        SLTU  R3, R1, R2
        STORE R3, R10, 4
        LI    R1, 0x00000002
        LI    R2, 0x00000001
        SLT   R3, R1, R2
        STORE R3, R10, 8
        SLTU  R3, R1, R2
        STORE R3, R10, 12
        LI    R1, 0xFFFFFFFF
        LI    R2, 0x00000001
        SLT   R3, R1, R2
        STORE R3, R10, 16
        SLTU  R3, R1, R2
        STORE R3, R10, 20
        LI    R1, 0x00000001
        LI    R2, 0xFFFFFFFF
        SLT   R3, R1, R2
        STORE R3, R10, 24
        SLTU  R3, R1, R2
        STORE R3, R10, 28
        LI    R1, 0x80000000
        LI    R2, 0x7FFFFFFF
        SLT   R3, R1, R2
        STORE R3, R10, 32
        SLTU  R3, R1, R2
        STORE R3, R10, 36
        LI    R1, 0x7FFFFFFF
        LI    R2, 0x80000000
        SLT   R3, R1, R2
        STORE R3, R10, 40
        SLTU  R3, R1, R2
        STORE R3, R10, 44
        LI    R1, 0x00000005
        LI    R2, 0x00000005
        SLT   R3, R1, R2
        STORE R3, R10, 48
        SLTU  R3, R1, R2
        STORE R3, R10, 52
        LI    R1, 0x00000000
        LI    R2, 0xFFFFFFFF
        SLT   R3, R1, R2
        STORE R3, R10, 56
        SLTU  R3, R1, R2
        STORE R3, R10, 60
        LI    R1, 0x80000000
        LI    R2, 0xFFFFFFFF
        SLT   R3, R1, R2
        STORE R3, R10, 64
        SLTU  R3, R1, R2
        STORE R3, R10, 68
        LI    R1, 0xFFFFFFFF
        LI    R2, 0x80000001
        SLT   R3, R1, R2
        STORE R3, R10, 72
        SLTU  R3, R1, R2
        STORE R3, R10, 76
        LI    R1, 0xFFFFFFFE
        LI    R2, 0xC0000000
        SLT   R3, R1, R2
        STORE R3, R10, 80
        SLTU  R3, R1, R2
        STORE R3, R10, 84
        LI    R1, 0x80000000
        LI    R2, 0x80000000
        SLT   R3, R1, R2
        STORE R3, R10, 88
        SLTU  R3, R1, R2
        STORE R3, R10, 92
        LI    R1, 0x00000064
        LI    R2, 0x00000007
        SLT   R3, R1, R2
        STORE R3, R10, 96
        SLTU  R3, R1, R2
        STORE R3, R10, 100
        LI    R1, 0xFFFFFF9C
        LI    R2, 0x00000007
        SLT   R3, R1, R2
        STORE R3, R10, 104
        SLTU  R3, R1, R2
        STORE R3, R10, 108
        LI    R1, 0x00000064
        LI    R2, 0xFFFFFFF9
        SLT   R3, R1, R2
        STORE R3, R10, 112
        SLTU  R3, R1, R2
        STORE R3, R10, 116
        LI    R1, 0x12345678
        LI    R2, 0x00010000
        SLT   R3, R1, R2
        STORE R3, R10, 120
        SLTU  R3, R1, R2
        STORE R3, R10, 124
        HALT
