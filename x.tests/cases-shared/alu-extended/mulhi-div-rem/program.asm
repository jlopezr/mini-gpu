; MULHI, DIV, DIVU, REM y REMU sobre pares de borde (divisor nunca cero).
; Incluye -2^31 / -1 y divisores por encima de 2^31.
        LI    R10, 0x1000
        LI    R1, 0x00000001
        LI    R2, 0x00000002
        MULHI R3, R1, R2
        STORE R3, R10, 0
        DIV   R3, R1, R2
        STORE R3, R10, 4
        DIVU  R3, R1, R2
        STORE R3, R10, 8
        REM   R3, R1, R2
        STORE R3, R10, 12
        REMU  R3, R1, R2
        STORE R3, R10, 16
        LI    R1, 0x00000002
        LI    R2, 0x00000001
        MULHI R3, R1, R2
        STORE R3, R10, 20
        DIV   R3, R1, R2
        STORE R3, R10, 24
        DIVU  R3, R1, R2
        STORE R3, R10, 28
        REM   R3, R1, R2
        STORE R3, R10, 32
        REMU  R3, R1, R2
        STORE R3, R10, 36
        LI    R1, 0xFFFFFFFF
        LI    R2, 0x00000001
        MULHI R3, R1, R2
        STORE R3, R10, 40
        DIV   R3, R1, R2
        STORE R3, R10, 44
        DIVU  R3, R1, R2
        STORE R3, R10, 48
        REM   R3, R1, R2
        STORE R3, R10, 52
        REMU  R3, R1, R2
        STORE R3, R10, 56
        LI    R1, 0x00000001
        LI    R2, 0xFFFFFFFF
        MULHI R3, R1, R2
        STORE R3, R10, 60
        DIV   R3, R1, R2
        STORE R3, R10, 64
        DIVU  R3, R1, R2
        STORE R3, R10, 68
        REM   R3, R1, R2
        STORE R3, R10, 72
        REMU  R3, R1, R2
        STORE R3, R10, 76
        LI    R1, 0x80000000
        LI    R2, 0x7FFFFFFF
        MULHI R3, R1, R2
        STORE R3, R10, 80
        DIV   R3, R1, R2
        STORE R3, R10, 84
        DIVU  R3, R1, R2
        STORE R3, R10, 88
        REM   R3, R1, R2
        STORE R3, R10, 92
        REMU  R3, R1, R2
        STORE R3, R10, 96
        LI    R1, 0x7FFFFFFF
        LI    R2, 0x80000000
        MULHI R3, R1, R2
        STORE R3, R10, 100
        DIV   R3, R1, R2
        STORE R3, R10, 104
        DIVU  R3, R1, R2
        STORE R3, R10, 108
        REM   R3, R1, R2
        STORE R3, R10, 112
        REMU  R3, R1, R2
        STORE R3, R10, 116
        LI    R1, 0x00000005
        LI    R2, 0x00000005
        MULHI R3, R1, R2
        STORE R3, R10, 120
        DIV   R3, R1, R2
        STORE R3, R10, 124
        DIVU  R3, R1, R2
        STORE R3, R10, 128
        REM   R3, R1, R2
        STORE R3, R10, 132
        REMU  R3, R1, R2
        STORE R3, R10, 136
        LI    R1, 0x00000000
        LI    R2, 0xFFFFFFFF
        MULHI R3, R1, R2
        STORE R3, R10, 140
        DIV   R3, R1, R2
        STORE R3, R10, 144
        DIVU  R3, R1, R2
        STORE R3, R10, 148
        REM   R3, R1, R2
        STORE R3, R10, 152
        REMU  R3, R1, R2
        STORE R3, R10, 156
        LI    R1, 0x80000000
        LI    R2, 0xFFFFFFFF
        MULHI R3, R1, R2
        STORE R3, R10, 160
        DIV   R3, R1, R2
        STORE R3, R10, 164
        DIVU  R3, R1, R2
        STORE R3, R10, 168
        REM   R3, R1, R2
        STORE R3, R10, 172
        REMU  R3, R1, R2
        STORE R3, R10, 176
        LI    R1, 0xFFFFFFFF
        LI    R2, 0x80000001
        MULHI R3, R1, R2
        STORE R3, R10, 180
        DIV   R3, R1, R2
        STORE R3, R10, 184
        DIVU  R3, R1, R2
        STORE R3, R10, 188
        REM   R3, R1, R2
        STORE R3, R10, 192
        REMU  R3, R1, R2
        STORE R3, R10, 196
        LI    R1, 0xFFFFFFFE
        LI    R2, 0xC0000000
        MULHI R3, R1, R2
        STORE R3, R10, 200
        DIV   R3, R1, R2
        STORE R3, R10, 204
        DIVU  R3, R1, R2
        STORE R3, R10, 208
        REM   R3, R1, R2
        STORE R3, R10, 212
        REMU  R3, R1, R2
        STORE R3, R10, 216
        LI    R1, 0x80000000
        LI    R2, 0x80000000
        MULHI R3, R1, R2
        STORE R3, R10, 220
        DIV   R3, R1, R2
        STORE R3, R10, 224
        DIVU  R3, R1, R2
        STORE R3, R10, 228
        REM   R3, R1, R2
        STORE R3, R10, 232
        REMU  R3, R1, R2
        STORE R3, R10, 236
        LI    R1, 0x00000064
        LI    R2, 0x00000007
        MULHI R3, R1, R2
        STORE R3, R10, 240
        DIV   R3, R1, R2
        STORE R3, R10, 244
        DIVU  R3, R1, R2
        STORE R3, R10, 248
        REM   R3, R1, R2
        STORE R3, R10, 252
        REMU  R3, R1, R2
        STORE R3, R10, 256
        LI    R1, 0xFFFFFF9C
        LI    R2, 0x00000007
        MULHI R3, R1, R2
        STORE R3, R10, 260
        DIV   R3, R1, R2
        STORE R3, R10, 264
        DIVU  R3, R1, R2
        STORE R3, R10, 268
        REM   R3, R1, R2
        STORE R3, R10, 272
        REMU  R3, R1, R2
        STORE R3, R10, 276
        LI    R1, 0x00000064
        LI    R2, 0xFFFFFFF9
        MULHI R3, R1, R2
        STORE R3, R10, 280
        DIV   R3, R1, R2
        STORE R3, R10, 284
        DIVU  R3, R1, R2
        STORE R3, R10, 288
        REM   R3, R1, R2
        STORE R3, R10, 292
        REMU  R3, R1, R2
        STORE R3, R10, 296
        LI    R1, 0x12345678
        LI    R2, 0x00010000
        MULHI R3, R1, R2
        STORE R3, R10, 300
        DIV   R3, R1, R2
        STORE R3, R10, 304
        DIVU  R3, R1, R2
        STORE R3, R10, 308
        REM   R3, R1, R2
        STORE R3, R10, 312
        REMU  R3, R1, R2
        STORE R3, R10, 316
        HALT
