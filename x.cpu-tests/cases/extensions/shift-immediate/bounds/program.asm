; SHLI / SHRI / SARI: los bordes de la cantidad y el modo aritmetico.
;
; Opcion B de propuesta-v0.2.md §4.2: no hay opcodes nuevos. SHL, SHR y SAR
; siguen siendo R-Type y el bit 10 del campo `extra` dice que la cantidad es
; inmediata, tomandola de los cinco bits del campo Rb.
;
; Lo que se comprueba aqui, ademas de los tres bordes obvios:
;
;   R4 vale 17 a proposito. Los desplazamientos de 4 usan el CAMPO, no el
;   registro numero 4, y con R4 valiendo 4 un mux al reves «funcionaria» igual.
;   Con R4 = 17, si el camino inmediato leyera el registro, el resultado saldria
;   desplazado 17 y el caso lo veria.

    MOVHI R1, 0x89AB
    ORI   R1, R1, 0xCDEF        ; R1 = 0x89ABCDEF, negativo

    MOVI  R4, 17                ; la trampa: R4 NO vale 4

    ; ---- cantidad 0: el borde que no da ni un paso ----
    SHLI  R2, R1, 0             ; 0x89ABCDEF
    SHRI  R3, R1, 0             ; 0x89ABCDEF
    SARI  R5, R1, 0             ; 0x89ABCDEF

    ; ---- cantidad 31: el otro borde ----
    SHLI  R6, R1, 31            ; 0x80000000
    SHRI  R7, R1, 31            ; 0x00000001
    SARI  R8, R1, 31            ; 0xFFFFFFFF

    ; ---- cantidad 4: el caso corriente, con R4 envenenado ----
    SHLI  R9, R1, 4             ; 0x9ABCDEF0
    SHRI  R10, R1, 4            ; 0x089ABCDE
    SARI  R11, R1, 4            ; 0xF89ABCDE

    ; ---- SARI sobre un positivo coincide con SHRI ----
    MOVHI R12, 0x1234
    ORI   R12, R12, 0x5678      ; R12 = 0x12345678
    SARI  R13, R12, 4           ; 0x01234567
    SHRI  R14, R12, 4           ; 0x01234567

    ; ---- la forma con registro sigue existiendo y da lo mismo ----
    MOVI  R15, 4
    SHL   R16, R1, R15          ; 0x9ABCDEF0
    SAR   R17, R1, R15          ; 0xF89ABCDE

    ; ---- SHLI 2 es el idioma que justifico la extension: indice -> offset ----
    MOVI  R18, 7
    SHLI  R19, R18, 2           ; 28, sin gastar un MOVI para el 2

    HALT
