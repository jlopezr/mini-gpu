; Código en 0x0000
; A: 16 palabras en 0x0100
; B: 16 palabras en 0x0140
; C: 16 palabras en 0x0180

GETTID R1           ; ID global: 0..15
MOVI   R2, 2
SHL    R3, R1, R2   ; desplazamiento en bytes = ID * 4

MOVI   R4, 0x0100
ADD    R4, R4, R3
LOAD   R5, R4, 0    ; A[ID]

MOVI   R6, 0x0140
ADD    R6, R6, R3
LOAD   R7, R6, 0    ; B[ID]

ADD    R8, R5, R7

MOVI   R9, 0x0180
ADD    R9, R9, R3
STORE  R8, R9, 0    ; C[ID]

HALT
