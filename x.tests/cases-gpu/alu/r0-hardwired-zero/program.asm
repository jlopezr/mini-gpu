; R0 esta cableado a cero: las escrituras se descartan y las lecturas valen 0.
MOVI R5, 4096
MOVI R6, 1234
STORE R6, R5, 0
MOVI R0, 77
ADDI R1, R0, 5
ADD R0, R6, R6
ADD R2, R0, R6
LOAD R0, R5, 0
ADD R3, R0, R0
SUB R0, R0, R6
ADD R4, R0, R0
HALT
