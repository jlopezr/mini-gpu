; R0 cableado a cero: escrituras descartadas, lecturas siempre cero.
;
; Esto NO es una extension: es una regla de la MiniISA, y la cumplen todas las
; implementaciones. Por eso el caso vive en `basics/` y no lleva `requires`.
;
; Lo fue durante un tiempo --la capacidad se llamaba `zero_register`-- mientras
; solo la tenia la 21. Fue ademas la unica capacidad no aditiva que ha tenido
; este runner, y por eso no podia quedarse asi: las demas se detectan porque un
; bitstream que no las tiene para con opcode invalido, y con R0 general no hay
; parada, hay otro resultado en silencio.
;
; Se ejercitan los caminos por los que la CPU escribe el banco, porque el puerto
; es uno pero los caminos son varios y es facil arreglar uno y olvidar los
; otros: MOVI/MOVHI/GETTID directos, la ALU registrada y el desplazador.
;
; El repertorio esta limitado al MINIMO COMUN de las seis implementaciones, que
; es la condicion para que un caso de `basics/` valga. Quedan fuera cuatro
; caminos de escritura, cada uno por un motivo distinto:
;
;   MUL y DIV      `10.fpga-cpu-ram` NO las implementa: declara los opcodes y
;                  valida su encoding, pero no tiene rama en el EXECUTE, asi
;                  que caen al `default` y dan ERROR_INVALID_OPCODE. Es un
;                  hueco anterior a todo esto, y el unico core que lo tiene.
;   LOAD           necesita memoria inicializada, que complica el caso sin
;                  anadir nada que no cubra ya el testbench.
;   el enlace de   es una extension, `calls`, que la 6 y la 10 no tienen.
;   JAL/JALR       Meterlo aqui obligaria a poner `requires` justo al caso que
;                  tiene que correr en todas partes.
;
; Los cuatro los cubre `zero_register_tb.v` de la 21, sobre el RTL, y el enlace
; ademas `extensions/calls/jalr-r0-is-jr`.

    MOVI  R1, 7
    MOVI  R2, 4

    ; ---- Los caminos de escritura, todos apuntando a R0 ----
    MOVI  R0, -1                ; directo
    MOVHI R0, 0xDEAD            ; directo
    ADD   R0, R1, R1            ; write-back de la ALU
    ADDI  R0, R1, 100           ; write-back de la ALU, inmediato
    SHL   R0, R1, R2            ; write-back del desplazador
    SHR   R0, R1, R2            ; write-back del desplazador, otra direccion
    SAR   R0, R1, R2            ; write-back del desplazador, aritmetico
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

    ; ---- R0 como destino de descarte: solo interesan los efectos ----
    ; Una operacion con destino R0 se retira sin error, no se salta.
    ADD   R0, R1, R2
    MOVI  R14, 5

    HALT
