; Kernel de gpu_core_tb: un warp que gira hasta que el banco pone un uno en
; [0x900]. Sirve para tener un warp vivo todo el tiempo que el banco quiera
; mientras prueba el lanzamiento de otros. El banco lo carga en 0x200.
kernel:
    LI    R5, 0x900
wait:
    LOAD  R1, R5, 0
    BEQ   R1, R0, wait
    HALT
