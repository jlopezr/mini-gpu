; Llamadas y saltos indirectos con un solo hilo: JAL, JALR y JR.
;
;   [0x1000] doble(5) por JAL y JR                      = 10
;   [0x1004] triple(7) por JALR con desplazamiento       = 21
;   [0x1008] enlace de JALR con Rd = Ra                  = direccion de la instruccion tras JALR
;   [0x100C] JR con los dos bits bajos del destino sucios = 4
        LI    R10, 0x1000
        MOVI  R4, 5
        JAL   R31, double
        STORE R4, R10, 0

        MOVI  R4, 7
        JAL   R5, base              ; R5 = &base
base:
        JALR  R31, R5, 18           ; destino = &base + 4*18 = triple
        STORE R4, R10, 4

        ; Rd = Ra: el destino se lee antes de escribir el enlace
        JAL   R6, here
here:
        JALR  R6, R6, 3             ; salta a `after`
        MOVI  R7, 111               ; no se ejecuta
        MOVI  R7, 222               ; no se ejecuta
after:
        STORE R6, R10, 8

        ; JR: el destino lleva 3 en los bits bajos y se alinea hacia abajo
        JAL   R8, target_base
target_base:
        ADDI  R8, R8, 23            ; &target_base + 20 + 3 sucio
        JR    R8
        MOVI  R9, 1                 ; no se ejecuta
        MOVI  R9, 2                 ; no se ejecuta
        MOVI  R9, 3                 ; no se ejecuta
        MOVI  R9, 4                 ; destino
        STORE R9, R10, 12
        HALT

double:
        ADD   R4, R4, R4
        JR    R31

triple:
        ADD   R11, R4, R4
        ADD   R4, R11, R4
        JR    R31
