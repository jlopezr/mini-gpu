; `JALR R0, Ra, 0` es un `JR Ra` completo, y por eso 0x2E queda obsoleto.
;
; Es la razon de peso para cablear R0 a cero --la otra son los idiomas--: la
; familia de control 0x20-0x2F estaba a CERO opcodes libres despues de
; propuesta-v0.2.md seccion 6, y esto devuelve uno al bote.
;
; `JR` no se ha quitado: sigue implementado y sigue siendo valido. Su hueco es
; *reclamable*, no libre. Quitarlo hoy romperia todo lo que usa `RET` sin ganar
; nada, porque el opcode todavia no hace falta.
;
; El caso comprueba las tres cosas que tienen que pasar a la vez:
;   1. el salto ocurre,
;   2. el enlace se descarta en vez de escribirse (R0 sigue a cero),
;   3. `JR` hace exactamente lo mismo.

    MOVI  R1, via_jalr
    JALR  R0, R1, 0
    MOVI  R2, 99                ; no se ejecuta
via_jalr:
    MOVI  R2, 42                ; el salto ocurrio

    ; El enlace habria sido la direccion de la instruccion siguiente al JALR,
    ; que no es cero. Si se hubiera escrito, R0 no valdria cero.
    ADD   R3, R0, R0            ; 0

    ; Y ahora lo mismo con JR, que tiene que coincidir.
    MOVI  R4, via_jr
    JR    R4
    MOVI  R5, 99                ; no se ejecuta
via_jr:
    MOVI  R5, 42

    ADD   R6, R0, R0            ; 0

    HALT
