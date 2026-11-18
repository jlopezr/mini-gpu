; FP32 compares and conversions (capability fp32). Bit patterns in integer registers.
LI R1, 0x3fc00000              ; 1.5
LI R2, 0x40100000              ; 2.25
LI R3, 0x7fc00000              ; NaN
LI R4, 0x80000000              ; -0
MOVI R5, 1                     ; smallest subnormal: compares are exact (no DAZ)
FLT R6, R1, R2                 ; 1
FLT R7, R2, R1                 ; 0
FLE R8, R1, R1                 ; 1
FEQ R9, R4, R0                 ; -0 == +0: 1
FEQ R10, R3, R3                ; NaN: 0
FLE R11, R3, R1                ; NaN: 0
FLT R12, R0, R5                ; 0 < subnormal: 1
LI R13, 0xc0100000             ; -2.25
FLT R14, R13, R1               ; 1
FTOI R15, R13                  ; -2 (truncates)
FTOI R16, R1, 16               ; 1.5 in Q16.16 = 0x18000
LI R17, 0x7f800000             ; +infinity
FTOI R18, R17                  ; 0x7fffffff
LI R19, 0xff800000             ; -infinity
FTOI R20, R19                  ; 0x80000000
FTOI R21, R3                   ; NaN: 0
LI R22, -3
ITOF R23, R22                  ; -3.0 = 0xc0400000
LI R24, 0x18000
ITOF R25, R24, 16              ; 1.5
LI R26, 0x7fffffff
ITOF R27, R26                  ; 2^31, rounded = 0x4f000000
ITOF R28, R0, 7                ; +0
FADD R29, R23, R25             ; -1.5: ITOF -> FADD
FTOI R30, R29, 1               ; -3
FLT R0, R1, R2                 ; discarded
HALT
