; Código en 0x0000
; A: 16 palabras en 0x0100
; B: 16 palabras en 0x0140
; C: 16 palabras en 0x0180
;
; Igual que el caso `vecsum`, pero el segundo warp arranca con máscara parcial.
; LOAD y STORE direccionan como base + desplazamiento inmediato.

GETTID R1           ; ID global: 0..15
MOVI   R2, 2
SHL    R3, R1, R2   ; desplazamiento en bytes = ID * 4

LOAD   R5, R3, 0x0100   ; A[ID]
LOAD   R7, R3, 0x0140   ; B[ID]

ADD    R8, R5, R7

STORE  R8, R3, 0x0180   ; C[ID]

HALT
