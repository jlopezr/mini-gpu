; REMU con divisor cero para igual que REM: ERROR_DIVISION_BY_ZERO (0x04).
;
; Va en un caso aparte del de REM porque los dos recorren ramas distintas del
; RTL --REMU no pasa los operandos por la negacion condicional-- y un arreglo
; que solo cubriera la rama con signo pasaria el otro caso sin enterarse.
;
; El PC observable queda en la instruccion culpable, la tercera: 0x00000008.

    MOVI  R1, 7
    MOVI  R2, 0
    REMU  R3, R1, R2
    HALT
