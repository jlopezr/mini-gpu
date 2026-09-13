; Tabla de saltos con JALR.
;
; Las tres rutinas ocupan dos palabras cada una a partir de 0x18, así que el
; índice de la tabla se convierte en desplazamiento multiplicándolo por dos: el
; inmediato de JALR cuenta **palabras**, como todo el control de flujo de esta
; ISA. Lo que se comprueba aquí es justamente esa escala, que es lo que rompe
; quien viene de RISC-V y la supone en bytes.
;
; La base va en un registro, no en el inmediato: es el caso que `BRA` no puede
; cubrir, porque su destino se fija al ensamblar.

        MOVI R5, 0x18             ; base de la tabla
        MOVI R6, 0                ; acumulador: una marca distinta por rutina
        JALR R31, R5, 0           ; entrada 0 -> 0x18
        JALR R31, R5, 2           ; entrada 1 -> 0x20
        JALR R31, R5, 4           ; entrada 2 -> 0x28
        HALT

        ; 0x18
        ADDI R6, R6, 1
        RET
        ; 0x20
        ADDI R6, R6, 0x10
        RET
        ; 0x28
        ADDI R6, R6, 0x100
        RET
