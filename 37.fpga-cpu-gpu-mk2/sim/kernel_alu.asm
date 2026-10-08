; Kernel de gpu_alu_tb: cada hilo lee un par (a, b) de dos tablas y deja en RAM el
; resultado de cada instruccion que se prueba. tid = warp*8 + lane, 4 warps.
;
;   a[tid]   en 0x800          b[tid]   en 0x900  (b nunca es cero: DIVU/REM)
;   SLT      en 0xA00          SLTU     en 0xB00
kernel:
    GETTID R1
    MOVI   R2, 2
    SHL    R3, R1, R2          ; desplazamiento en bytes
    LOAD   R6, R3, 0x800       ; a
    LOAD   R7, R3, 0x900       ; b

    SLT    R8, R6, R7
    STORE  R8, R3, 0xA00
    SLTU   R8, R6, R7
    STORE  R8, R3, 0xB00
    HALT
