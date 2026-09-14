; Las secuencias en las que el camino rapido de la 21 NO debe acertar.
;
; ==========================================================================
; Por que existe este caso si el camino rapido es invisible
; ==========================================================================
;
; Precisamente por eso. La 21 puede saltarse el calculo de un MULHI, un REM o un
; REMU cuando la instruccion INMEDIATAMENTE anterior fue su MUL, su DIV o su
; DIVU con los mismos numeros de registro. Es una optimizacion de ciclos y nada
; mas: el numero que sale tiene que ser el mismo haya acierto o no.
;
; El riesgo de esa optimizacion no es que rompa algo ruidosamente. Es que un
; acierto indebido devuelva un valor PLAUSIBLE y equivocado en ciertas
; secuencias y solo en ellas. Este programa reune esas secuencias --las de
; FALLO-- y fija el resultado correcto de cada una.
;
; El grueso de la comprobacion no esta aqui sino en
; 21.fpga-cpu-hdmi-alu/alu_fast_path_tb.v, que ejecuta programas en dos CPUs a
; la vez, una con el atajo y otra sin el, y compara los 32 registros. Lo que
; anade este caso es que la misma secuencia se comprueba tambien contra el
; simulador funcional, que no modela nada de esto: si el RTL se colara, el
; diferencial `--backend both` lo veria.
;
; Los ciclos NO se comprueban aqui, y no se puede: el simulador no los tiene y
; el runner ya los excluye de la comparacion diferencial.

    MOVI  R1, -7
    MOVI  R2, 2
    MOVI  R3, 4
    MOVHI R4, 0x1234
    ORI   R4, R4, 0x5678        ; R4 = 0x12345678

    ; ---- Instruccion intercalada: la condicion es «la anterior», no «alguna» -
    DIV   R5, R1, R2            ; -3
    NOP
    REM   R6, R1, R2            ; -1, recalculado

    ; ---- Operandos distintos: mismo DIV, otro divisor --------------------
    DIV   R7, R1, R2            ; -3
    REM   R8, R1, R3            ; -7 rem 4 = -3; el resto viejo era -1

    ; ---- Tipo cruzado: REM detras de un MUL de los mismos numeros --------
    ; El MUL deja un producto, no un resto. Un acierto aqui daria basura.
    MUL   R9, R1, R2            ; -14
    REM   R10, R1, R2           ; -1

    ; ---- Tipo cruzado: MULHI detras de un DIV ----------------------------
    DIV   R11, R1, R2           ; -3
    MULHI R12, R1, R2           ; alto de -7 x 2 = -14 -> 0xFFFFFFFF

    ; ---- Signo cruzado: REM detras de un DIVU con dividendo negativo -----
    ; DIVU trabaja con los bits crudos y DIV con magnitudes, asi que el resto
    ; que deja un DIVU no es el que quiere un REM. Si los dos tipos fueran uno
    ; solo, R14 saldria 1 en vez de -1.
    DIVU  R13, R1, R2           ; 0x7FFFFFFC
    REM   R14, R1, R2           ; -1

    ; ---- Y al reves: REMU detras de un DIV con signo ---------------------
    DIV   R15, R1, R2           ; -3
    REMU  R16, R1, R2           ; 4294967289 rem 2 = 1

    ; ---- `rd` pisa una fuente: los numeros coinciden, los valores no ------
    ; Es el unico caso en el que comparar numeros de registro de 5 bits no
    ; basta, y por eso el armado lo excluye a mano. Los valores estan elegidos
    ; para que el resto viejo y el nuevo NO coincidan: si coincidieran, el caso
    ; pasaria con la etiqueta rota.
    MOVI  R17, 9
    DIV   R17, R17, R2          ; R17 = 4, pisando el dividendo; resto viejo 1
    REM   R18, R17, R2          ; 4 rem 2 = 0

    ; ---- `rd` pisa el divisor --------------------------------------------
    MOVI  R31, 10
    MOVI  R19, 4
    DIV   R19, R31, R19         ; R19 = 2, pisando el divisor; resto viejo 2
    REM   R20, R31, R19         ; 10 rem 2 = 0

    ; ---- MULFX no arma: multiplica MAGNITUDES ----------------------------
    ; Un MULHI que se creyera el producto que deja MULFX daria el valor
    ; absoluto del alto. Con un operando negativo eso se ve.
    MULFX R21, R1, R4           ; Q16.16
    MULHI R22, R1, R4           ; alto signed de -7 x 0x12345678

    ; ---- Arranque en frio: MULHI y REM sin nada delante ------------------
    NOP
    MULHI R23, R1, R2           ; 0xFFFFFFFF
    NOP
    REM   R24, R1, R2           ; -1

    ; ---- Y los aciertos de verdad, que tienen que dar lo mismo -----------
    MUL   R25, R1, R4
    MULHI R26, R1, R4           ; igual que R22
    DIV   R27, R1, R2
    REM   R28, R1, R2           ; igual que R6, R10, R14, R24
    DIVU  R29, R1, R2
    REMU  R30, R1, R2           ; igual que R16

    HALT
