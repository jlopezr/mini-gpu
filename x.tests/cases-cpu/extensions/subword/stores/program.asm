; STOREB y STOREH tocan solo sus bytes.
;
; El dato se replica en los cuatro carriles de la palabra y es la máscara de
; byte la que elige cuál vale, así que un fallo en la máscara se ve como bytes
; vecinos pisados. Por eso dos de las tres palabras de partida son 0xFFFFFFFF:
; sobre ceros, escribir de más pasaría desapercibido.
;
; Se escribe siempre desde registros con los 32 bits distintos de cero, para
; comprobar también que STOREB usa solo R[7:0] y STOREH solo R[15:0].

        MOVHI  R1, 0x0010
        ADDI   R1, R1, 0x0400     ; 0x00100400

        MOVHI  R2, 0xAAAA
        ORI    R2, R2, 0xAAAA     ; 0xAAAAAAAA
        STOREB R2, R1, 1          ; byte 1 de la palabra 0
        STOREB R2, R1, 2          ; byte 2 de la palabra 0

        MOVHI  R3, 0x1234
        ORI    R3, R3, 0x5678     ; 0x12345678
        STOREH R3, R1, 4          ; mitad baja de la palabra 1
        STOREH R3, R1, 10         ; mitad alta de la palabra 2

        HALT
