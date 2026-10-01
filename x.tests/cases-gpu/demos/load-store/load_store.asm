; Independent words per thread; stresses LSU/RF overlap without memory races.
GETTID R1
MOVI R6,4
MUL R2,R1,R6
ADDI R2,R2,4096
MOVI R3,32
loop:
LOAD R4,R2,0
ADDI R5,R4,1
STORE R5,R2,0
ADDI R3,R3,-1
BNE R3,R0,loop
BAR
EXIT
