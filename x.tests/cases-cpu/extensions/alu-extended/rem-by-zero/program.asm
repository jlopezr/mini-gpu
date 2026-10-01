; REM con divisor cero para con ERROR_DIVISION_BY_ZERO (0x04), igual que DIV.
;
; El resto no tiene mas definicion que la division que lo acompana, asi que no
; hay nada que devolver cuando la division no existe. La ISA ya decia que la
; division por cero es un trap arquitectonico; REM hereda esa regla sin
; excepciones.
;
; El PC observable queda en la instruccion culpable, la cuarta: 0x0000000C.

    MOVI  R1, 7
    MOVI  R2, 0
    NOP
    REM   R3, R1, R2
    HALT
