; Cada hilo copia una palabra; dos warps cubren 16 palabras.
; La base de cada vector viaja en el desplazamiento inmediato de LOAD/STORE.
GETTID R1
MOVI R2, 2
SHL R3, R1, R2
LOAD R5, R3, 256
STORE R5, R3, 384
HALT
