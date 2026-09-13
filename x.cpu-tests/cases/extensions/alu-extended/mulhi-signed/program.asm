; MULHI: la parte alta del producto, CON SIGNO.
;
; La decision esta escrita en 1.isa/isa.md §3 y razonada en
; 21.fpga-cpu-hdmi-alu/docs/alu-extendida.md. Importa aqui porque el producto de
; 64 bits que construye el RTL es el UNSIGNED: la mitad alta signed necesita una
; correccion, y sin ella todos los casos con operandos positivos seguirian
; saliendo bien. Por eso casi todos los pares de este programa llevan al menos
; un negativo.
;
; El par mas util es -1 x -1: signed da 1, o sea parte alta 0x00000000, y
; unsigned daria 0xFFFFFFFE. Un MULHI unsigned se cae ahi y en ningun otro sitio
; del programa.

    MOVHI R1, 0x1234
    ORI   R1, R1, 0x5678        ; R1 = 0x12345678, positivo
    MOVHI R2, 0x9ABC
    ORI   R2, R2, 0xDEF0        ; R2 = 0x9ABCDEF0, negativo

    ; MUL y MULHI pegados: las dos mitades del mismo producto de 64 bits.
    ; Es ademas el idioma que dispara el camino rapido, que no debe cambiar
    ; el resultado --solo los ciclos, que el diferencial no compara--.
    MUL   R3, R1, R2            ; 0x242D2080
    MULHI R4, R1, R2            ; 0xF8CC93D6

    ; El mismo MULHI con una instruccion enmedio: el camino rapido falla y se
    ; recalcula. Tiene que dar exactamente lo mismo que R4.
    NOP
    MULHI R5, R1, R2            ; 0xF8CC93D6

    ; Conmutado.
    MULHI R6, R2, R1            ; 0xF8CC93D6

    ; -1 x -1 = 1. Signed: alto 0. Unsigned habria dado 0xFFFFFFFE.
    MOVI  R7, -1
    MULHI R8, R7, R7            ; 0x00000000
    MUL   R9, R7, R7            ; 0x00000001

    ; -1 x 1 = -1: los 64 bits a uno.
    MOVI  R10, 1
    MULHI R11, R7, R10          ; 0xFFFFFFFF
    MUL   R12, R7, R10          ; 0xFFFFFFFF

    ; El minimo negativo al cuadrado: (-2^31)^2 = 2^62.
    MOVHI R13, 0x8000           ; R13 = 0x80000000
    MULHI R14, R13, R13         ; 0x40000000
    MUL   R15, R13, R13         ; 0x00000000

    ; -2^31 x 1 = -2^31, que no cabe en la mitad baja con su signo.
    MULHI R16, R13, R10         ; 0xFFFFFFFF
    MUL   R17, R13, R10         ; 0x80000000

    ; 2^16 x 2^16 = 2^32: el acarreo justo en la frontera entre las dos mitades.
    MOVHI R18, 0x0001           ; R18 = 0x00010000
    MULHI R19, R18, R18         ; 0x00000001
    MUL   R20, R18, R18         ; 0x00000000

    ; Un producto que cabe entero abajo: el alto es cero, no basura.
    MOVI  R21, 3
    MOVI  R22, 5
    MULHI R23, R21, R22         ; 0x00000000
    MUL   R24, R21, R22         ; 0x0000000F

    HALT
