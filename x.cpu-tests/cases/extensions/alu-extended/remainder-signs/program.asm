; DIV, DIVU, REM y REMU: las cuatro combinaciones de signo, y unsigned frente
; a signed sobre el mismo patron de bits.
;
; La regla que se fija aqui: el resto acompana a una division truncada hacia
; cero, asi que lleva el signo del DIVIDENDO, no el del cociente ni el del
; divisor. `rem = a - (a/b)*b` en todos los casos.
;
;   7 /  2 =  3, resto  1
;  -7 /  2 = -3, resto -1
;   7 / -2 = -3, resto  1
;  -7 / -2 =  3, resto -1
;
; Los dos de enmedio son los que separan esta regla de la otra convencion
; posible --el resto con el signo del divisor, que es el modulo matematico--,
; que daria 1 y -1 en lugar de -1 y 1.
;
; Cada DIV va seguido de su REM, que es como lo emite el codigo real y lo que
; dispara el camino rapido. Los ultimos bloques mezclan el orden a proposito.

    MOVI  R1, 7
    MOVI  R2, 2
    MOVI  R3, -7
    MOVI  R4, -2

    ;  7 /  2
    DIV   R5, R1, R2            ; 3
    REM   R6, R1, R2            ; 1
    ; -7 /  2
    DIV   R7, R3, R2            ; -3 = 0xFFFFFFFD
    REM   R8, R3, R2            ; -1 = 0xFFFFFFFF
    ;  7 / -2
    DIV   R9, R1, R4            ; -3
    REM   R10, R1, R4           ; 1
    ; -7 / -2
    DIV   R11, R3, R4           ; 3
    REM   R12, R3, R4           ; -1

    ; Los mismos bits, sin signo. 0xFFFFFFF9 son 4294967289, no -7.
    DIVU  R13, R3, R2           ; 0x7FFFFFFC
    REMU  R14, R3, R2           ; 1
    ; Y aqui signed y unsigned se separan del todo: -7 / -2 da 3, mientras que
    ; 4294967289 / 4294967294 da 0 con resto 4294967289.
    DIVU  R15, R3, R4           ; 0
    REMU  R16, R3, R4           ; 0xFFFFFFF9

    ; REMU detras de un DIV con signo: tipo cruzado. El resto que dejo el DIV es
    ; el de las magnitudes y NO sirve; hay que recalcular. Si el camino rapido
    ; no distinguiera signed de unsigned, R18 saldria 1 en vez de 0xFFFFFFF9.
    DIV   R17, R3, R4           ; 3
    REMU  R18, R3, R4           ; 0xFFFFFFF9

    ; El desbordamiento clasico: -2^31 / -1 no cabe en signed32 y hace wrap.
    ; El resto es cero, que es lo unico que no sorprende del caso.
    MOVHI R19, 0x8000           ; R19 = 0x80000000
    MOVI  R20, -1
    DIV   R21, R19, R20         ; 0x80000000
    REM   R22, R19, R20         ; 0

    ; Divisor mayor que el dividendo: cociente cero, resto el dividendo entero.
    MOVI  R23, 5
    MOVI  R24, 7
    DIV   R25, R23, R24         ; 0
    REM   R26, R23, R24         ; 5

    ; Dividendo cero. El cero sale de un MOVI y no de R0 a proposito: este caso
    ; solo requiere `alu_extended`, y apoyarse en R0 lo ataria ademas a
    ; `zero_register`, que es una extension distinta.
    MOVI  R27, 0
    DIV   R28, R27, R24         ; 0
    REM   R29, R27, R24         ; 0

    ; Resto exacto: sin residuo el resto es cero, no el divisor.
    MOVI  R30, 12
    MOVI  R31, 3
    REM   R27, R30, R31         ; 0

    HALT
