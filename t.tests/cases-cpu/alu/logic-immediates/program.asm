; ANDI/XORI/ORI extienden el inmediato con CEROS, no con signo (isa.md).
; XOR completa la familia lógica registro-registro.

        MOVI  R1, -1            ; 0xFFFFFFFF

        ANDI  R2, R1, 0xFFFF    ; zero_extend => 0x0000FFFF
                                ; con sign_extend saldria 0xFFFFFFFF
        XORI  R3, R1, 0xFFFF    ; zero_extend => 0xFFFF0000
                                ; con sign_extend saldria 0x00000000

        MOVHI R4, 0x1234
        ORI   R4, R4, 0x5678    ; 0x12345678

        XOR   R5, R4, R1        ; complemento a 1: 0xEDCBA987
        XOR   R6, R4, R4        ; a XOR a = 0
        XORI  R7, R4, 0         ; identidad

        ANDI  R8, R4, 0x00FF    ; 0x78

        HALT
