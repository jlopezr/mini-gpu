; Una media palabra en dirección impar es un acceso inválido.
;
; El byte no tiene alineación que respetar, pero la media palabra sí, y quien
; lo comprueba es la CPU: es la única que conoce el tamaño del acceso. El
; adaptador de memoria ya no exige dirección múltiplo de cuatro, así que sin
; este trap la petición llegaría al bus partida entre dos palabras.
;
; El PC observable queda en la instrucción culpable, no en la siguiente.

        MOVHI R1, 0x0010
        ADDI  R1, R1, 0x0400
        LOADH R2, R1, 1           ; 0x08: 0x00100401, impar
        HALT
