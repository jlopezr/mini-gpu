; Codigo en 0x0000
; IN:   8 palabras en 0x0140
; OUT:  8 palabras en 0x0100   (OUT[tid] = tid + 1)
; COPY: 8 palabras en 0x0180   (COPY[tid] = IN[tid])
;
; LOAD y STORE con desplazamiento inmediato NEGATIVO. La direccion de cada lane
; es base + inmediato extendido en signo (0xFFFFFFxx): una suma de 32 bits que
; acarrea en la lane n no debe sumar nada a la lane n+1. Con la base en 0x0200
; todas las lanes acarrean, asi que una LSU que sume las ocho lanes como UN
; solo numero de 256 bits da direcciones desalineadas (+1 byte por lane) y falla.

GETTID R1            ; 0..7
MOVI   R2, 2
SHL    R3, R1, R2    ; tid * 4
ADDI   R4, R3, 0x0200
ADDI   R5, R1, 1

STORE  R5, R4, -256  ; OUT[tid]  en 0x0100
LOAD   R6, R4, -192  ; IN[tid]   desde 0x0140
STORE  R6, R4, -128  ; COPY[tid] en 0x0180

HALT
