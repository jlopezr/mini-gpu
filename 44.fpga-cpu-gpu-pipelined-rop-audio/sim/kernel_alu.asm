; Kernel de gpu_alu_tb: cada hilo lee un par (a, b) de dos tablas y deja en RAM el
; resultado de cada instruccion que se prueba. tid = warp*8 + lane, 4 warps.
;
;   a[tid]   en 0x800          b[tid]   en 0x900  (b nunca es cero: DIV/REM)
;   SLT      en 0xA00          SLTU     en 0xB00
;   MULHI    en 0xC00          DIV      en 0xD00
;   DIVU     en 0xE00          REM      en 0xF00
;   REMU     en 0x1000
;   SHLI a,5 en 0x1100         SHRI a,31 en 0x1200
;   SARI a,9 en 0x1300         SHLI a,0  en 0x1400
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
    MULHI  R8, R6, R7
    STORE  R8, R3, 0xC00
    DIV    R8, R6, R7
    STORE  R8, R3, 0xD00
    DIVU   R8, R6, R7
    STORE  R8, R3, 0xE00
    REM    R8, R6, R7
    STORE  R8, R3, 0xF00
    REMU   R8, R6, R7
    STORE  R8, R3, 0x1000

    SHLI   R8, R6, 5
    STORE  R8, R3, 0x1100
    SHRI   R8, R6, 31
    STORE  R8, R3, 0x1200
    SARI   R8, R6, 9
    STORE  R8, R3, 0x1300
    SHLI   R8, R6, 0
    STORE  R8, R3, 0x1400
    HALT
