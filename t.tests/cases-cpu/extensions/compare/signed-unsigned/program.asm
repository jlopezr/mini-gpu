; SLT y SLTU: el mismo par de bits da respuestas distintas segun se lea con
; signo o sin el. R2 = 0xFFFFFFFF es -1 en signed y el mayor valor en unsigned;
; es el operando que separa las dos instrucciones.

    MOVI  R1, 5
    MOVHI R2, 0xFFFF
    ORI   R2, R2, 0xFFFF        ; R2 = 0xFFFFFFFF = -1

    SLT   R3, R1, R2            ; 5 < -1 con signo: 0
    SLTU  R4, R1, R2            ; 5 < 0xFFFFFFFF sin signo: 1

    SLT   R5, R2, R1            ; -1 < 5 con signo: 1
    SLTU  R6, R2, R1            ; 0xFFFFFFFF < 5 sin signo: 0

    MOVI  R7, 0
    SLT   R8, R7, R2            ; 0 < -1 con signo: 0
    SLTU  R9, R7, R2            ; 0 < 0xFFFFFFFF sin signo: 1

    SLT   R10, R1, R1           ; iguales: 0
    SLTU  R11, R1, R1           ; iguales: 0

    ; El overflow clasico de un SLT mal hecho: INT_MAX - INT_MIN desborda el
    ; rango signed de 32 bits, asi que un comparador que solo mirara el bit de
    ; signo de la resta (en vez de los signos de los operandos por separado)
    ; diria que INT_MAX < INT_MIN. La respuesta con signo es 0.
    MOVHI R12, 0x7FFF
    ORI   R12, R12, 0xFFFF      ; R12 = 0x7FFFFFFF = INT_MAX
    MOVHI R13, 0x8000           ; R13 = 0x80000000 = INT_MIN
    SLT   R14, R12, R13         ; INT_MAX < INT_MIN con signo: 0
    SLTU  R15, R12, R13         ; INT_MAX < INT_MIN sin signo: 1

    HALT
