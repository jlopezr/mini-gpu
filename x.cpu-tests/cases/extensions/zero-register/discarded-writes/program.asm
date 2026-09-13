; R0 cableado a cero: escrituras descartadas, lecturas siempre cero.
;
; Este caso es distinto de los otros de `extensions/`, y conviene tenerlo claro
; al leerlo: las demas extensiones son ADITIVAS --un backend sin ellas para con
; error 0x01 y se nota-- y esta es INCOMPATIBLE. En un backend donde R0 sea un
; registro general este programa no falla: sale otro resultado, en silencio. Por
; eso lleva `requires: ["zero_register"]` y por eso se omite en vez de fallar en
; los bitstreams anteriores.
;
; Se ejercitan los seis caminos por los que la CPU escribe el banco, porque el
; puerto es uno pero los caminos son varios y es facil arreglar uno y olvidar
; los otros: MOVI/MOVHI/GETTID directos, la ALU registrada, el desplazador, el
; multiplicador/divisor y el enlace de las llamadas. El LOAD no entra aqui
; --necesita memoria inicializada, y el testbench zero_register_tb.v ya lo
; cubre--.

    MOVI  R1, 7
    MOVI  R2, 4

    ; ---- Los caminos de escritura, todos apuntando a R0 ----
    MOVI  R0, -1                ; directo
    MOVHI R0, 0xDEAD            ; directo
    ADD   R0, R1, R1            ; STATE_ALU_WRITE
    ADDI  R0, R1, 100           ; STATE_ALU_WRITE, inmediato
    SHL   R0, R1, R2            ; STATE_SHIFT_WRITE
    MUL   R0, R1, R1            ; STATE_MUL_WRITE, por el multiplicador
    DIV   R0, R1, R2            ; STATE_MUL_WRITE, por el divisor
    GETTID R0                   ; directo

    ; R0 sigue valiendo cero despues de las ocho.
    ADD   R3, R0, R0            ; 0
    ADDI  R4, R0, 42            ; 42, o sea R0 leido como cero

    ; ---- Una escritura descartada no deja rastro en la instruccion siguiente -
    MOVI  R0, 99
    ADD   R5, R0, R1            ; 7, no 106

    ; ---- R0 leido vale cero en los dos puertos y en las dos posiciones ----
    SUB   R6, R1, R0            ; 7
    SUB   R7, R0, R1            ; -7

    ; ---- El idioma barato: comparar con cero sin gastar un MOVI ----
    MOVI  R8, 1
    BEQ   R0, R0, r0_igual_a_r0
    MOVI  R8, 99                ; no se ejecuta
r0_igual_a_r0:
    MOVI  R9, 1
    SUB   R10, R1, R1           ; 0
    BNE   R10, R0, r0_distinto  ; no se toma: los dos valen cero
    MOVI  R9, 5
r0_distinto:

    ; ---- La razon del cambio: JALR R0 es un JR completo ----
    ; El enlace se descarta, el salto ocurre, y con eso el opcode 0x2E queda
    ; obsoleto y su hueco reclamable. JR sigue implementado --quitarlo hoy
    ; rompe programas sin ganar nada-- y aqui se ve que los dos coinciden.
    MOVI  R11, destino
    JALR  R0, R11, 0
    MOVI  R12, 99               ; no se ejecuta
destino:
    MOVI  R12, 42

    ; R0 sigue a cero despues del JALR: el enlace no se cuelo.
    ADD   R13, R0, R0           ; 0

    ; ---- R0 como destino de descarte: solo interesan los efectos ----
    ; Una division valida con destino R0 se retira sin error.
    DIV   R0, R1, R2
    MOVI  R14, 5

    HALT
