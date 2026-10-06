; Una media palabra en direccion impar es un acceso invalido.
;
; El byte no tiene alineacion que respetar, pero la media palabra si: la LSU lo
; comprueba con el tamano del acceso. Sin esa comprobacion la peticion llegaria
; a la memoria partida entre dos palabras.
;
; El PC observable queda en la instruccion culpable, no en la siguiente.
    MOVI  R1, 4097              ; 0x1001, impar
    LOADUB R3, R1, 0            ; un byte en direccion impar es legal
    LOADH R2, R1, 0             ; 0x08: media palabra en direccion impar
    HALT
