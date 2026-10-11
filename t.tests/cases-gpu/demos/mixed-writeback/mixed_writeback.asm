; Warps 0..3 load; warps 4..7 compute. Uniform branch within each warp.
GETTID R1
MOVI R2,32
BLT R1,R2,memory
MOVI R3,256
compute_loop:
ADDI R4,R4,1
ADDI R3,R3,-1
BNE R3,R0,compute_loop
BRA done
memory:
MOVI R3,32
memory_loop:
LOAD R5,R0,4096
ADDI R3,R3,-1
BNE R3,R0,memory_loop
done:
BAR
EXIT
