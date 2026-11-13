; EXT (0x1E): MIN/MAX/MINU/MAXU (capability minmax) and CLZ (capability clz).
LI R1, -5
MOVI R2, 7
MIN R3, R1, R2                 ; -5
MAX R4, R1, R2                 ; 7
MINU R5, R1, R2                ; 7 (-5 is 0xfffffffb unsigned)
MAXU R6, R1, R2                ; 0xfffffffb
MIN R7, R2, R2                 ; same register
CLZ R8, R0                     ; 32
CLZ R9, R1                     ; 0
CLZ R10, R2                    ; 29
LI R11, 0x00010000
CLZ R12, R11                   ; 15
MIN R13, R3, R4                ; dependent: -5
CLZ R14, R13                   ; dependent: 0
MAX R0, R1, R2                 ; discarded
HALT
