; Llamada, retorno y anidamiento.
;
; `R31` es el registro de enlace por convención, no por hardware, así que una
; llamada dentro de otra lo machaca. `outer` lo salva en memoria antes de llamar
; a `inner` y lo restaura antes de volver: sin eso, su RET saltaría a su propia
; llamada anidada y el programa daría vueltas para siempre.
;
; No hay pila: `R1` apunta a una palabra suelta, que es cuanto necesita una
; anidación de un nivel.

        MOVHI R1, 0x0010
        ADDI  R1, R1, 0x0400      ; 0x00100400, hueco para el enlace salvado
        JAL   R31, outer
        MOVI  R20, 0x1111         ; se ejecuta al volver de outer
        HALT

outer:
        STORE R31, R1, 0
        MOVI  R11, 0x2222
        JAL   R31, inner
        MOVI  R12, 0x3333
        LOAD  R31, R1, 0
        RET                       ; alias de JR R31

inner:
        MOVI  R13, 0x4444
        RET
