; FP32 bit patterns live in the ordinary integer registers.
LI R1, 0x3fc00000              ; 1.5
LI R2, 0x40100000              ; 2.25
FADD R3, R1, R2                ; 3.75
FSUB R4, R3, R1                ; 2.25, dependent on FADD
FMUL R5, R4, R1                ; 3.375
FDIV R6, R5, R1                ; 2.25
ADDI R20, R0, 0x1000
STORE R6, R20, 0
LOAD R7, R20, 0
FADD R8, R7, R1                ; load -> FP, 3.75
FDIV R9, R1, R0                ; +infinity, no integer division fault
FDIV R10, R0, R0               ; canonical NaN
FDIV R0, R1, R0                ; discarded result, R0 remains zero
LI R11, 0x80000000
FMUL R12, R11, R1              ; -zero
MOVI R13, 1                    ; positive subnormal, treated as +zero
FMUL R14, R13, R1              ; +zero
LI R15, 0x00800000             ; smallest normal
LI R16, 0x3f000000             ; 0.5
FMUL R17, R15, R16             ; underflow -> +zero
LI R18, 0x7f7fffff             ; largest finite
FDIV R19, R18, R15             ; overflow -> +infinity
FSUB R21, R1, R1               ; cancellation -> +zero
LI R22, 0x3f800000
LI R23, 0x40400000
FDIV R24, R22, R23             ; 1/3, rounded
HALT
