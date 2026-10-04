; Lee siete eventos de INPUT (mmio.md §25) y deja cada palabra en un registro.
;
;   R10, R11   Shift+A pulsadas a la vez: MODIFIERS, y A down con el modificador
;   R12, R13   las dos se sueltan: A up (con los modificadores nuevos) y MODIFIERS
;   R14, R15   botón izquierdo down y movimiento (3, -2) en un mismo report
;   R16        botón izquierdo up
;   R17        STATUS final    R18  KEY_STATE0    R19  MOUSE_BUTTONS
;
; Cada espera sondea STATUS.COUNT (bits 15:0): el valor leído de EVENT_DATA no
; dice si había evento, COUNT sí.

        MOVHI R1, 0x8060            ; base de INPUT

w0:     LOAD  R3, R1, 4
        ANDI  R3, R3, 0xFF
        BEQ   R3, R0, w0
        LOAD  R10, R1, 0
w1:     LOAD  R3, R1, 4
        ANDI  R3, R3, 0xFF
        BEQ   R3, R0, w1
        LOAD  R11, R1, 0
w2:     LOAD  R3, R1, 4
        ANDI  R3, R3, 0xFF
        BEQ   R3, R0, w2
        LOAD  R12, R1, 0
w3:     LOAD  R3, R1, 4
        ANDI  R3, R3, 0xFF
        BEQ   R3, R0, w3
        LOAD  R13, R1, 0
w4:     LOAD  R3, R1, 4
        ANDI  R3, R3, 0xFF
        BEQ   R3, R0, w4
        LOAD  R14, R1, 0
w5:     LOAD  R3, R1, 4
        ANDI  R3, R3, 0xFF
        BEQ   R3, R0, w5
        LOAD  R15, R1, 0
w6:     LOAD  R3, R1, 4
        ANDI  R3, R3, 0xFF
        BEQ   R3, R0, w6
        LOAD  R16, R1, 0

        LOAD  R17, R1, 4            ; STATUS
        LOAD  R18, R1, 0x10         ; KEY_STATE0
        LOAD  R19, R1, 0x30         ; MOUSE_BUTTONS
        HALT
