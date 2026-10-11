; "Para SHL, SHR y SAR, la cantidad de desplazamiento seran los cinco bits
; bajos de Rb" (isa.md). Ademas SAR debe replicar el bit de signo mientras que
; SHR mete ceros.

        MOVHI R1, 0x8000        ; R1 = 0x80000000 (negativo)
        MOVI  R2, 4

        SAR   R3, R1, R2        ; aritmetico: 0xF8000000
        SHR   R4, R1, R2        ; logico:     0x08000000

        MOVI  R5, 32            ; 32 & 31 = 0: desplazamiento nulo
        SAR   R6, R1, R5        ; 0x80000000, sin cambios
        SHL   R7, R1, R5        ; 0x80000000, sin cambios

        MOVI  R8, 33            ; 33 & 31 = 1
        MOVI  R9, 1
        SHL   R10, R9, R8       ; 1 << 1 = 2
        SHR   R11, R1, R8       ; 0x40000000

        MOVI  R12, 31
        SAR   R13, R1, R12      ; signo replicado hasta el final: 0xFFFFFFFF
        SHR   R14, R1, R12      ; solo queda el bit alto: 0x00000001

        HALT
