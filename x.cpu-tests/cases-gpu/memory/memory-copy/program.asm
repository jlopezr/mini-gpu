; Cada hilo copia una palabra; dos warps cubren 16 palabras.
GETTID R1
MOVI R2, 2
SHL R3, R1, R2
MOVI R4, 256
ADD R4, R4, R3
LOAD R5, R4, 0
MOVI R6, 384
ADD R6, R6, R3
STORE R5, R6, 0
HALT
