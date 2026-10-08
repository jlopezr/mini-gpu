; Kernel de prueba de la 36: out[tid] = tid*tid + 1, tid = warp*8 + lane.
; Mismo kernel que 32.cpu-gpu-func-sim/examples/asm/launch.asm, pero solo la parte
; de la GPU: el banco carga esta imagen en RAM y lanza los warps por MMIO.
kernel:
    GETTID R1
    MUL    R2, R1, R1
    ADDI   R2, R2, 1
    MOVI   R3, 2
    SHL    R4, R1, R3
    LI     R5, 0x400
    ADD    R4, R4, R5
    STORE  R2, R4, 0
    HALT
