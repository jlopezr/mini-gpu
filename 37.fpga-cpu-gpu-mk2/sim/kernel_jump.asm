; Kernel de gpu_jump_tb, fase 1: llamadas y saltos indirectos con todos los hilos
; de acuerdo. tid = warp*8 + lane, 4 warps. Cada hilo deja cuatro palabras:
;
;   0xA00  doble(5) por JAL/JR           = 10
;   0xB00  triple(tid) por JALR          = 3*tid
;   0xC00  enlace de JAL, Rd = Ra        = direccion de la instruccion siguiente
;   0xD00  camino tomado con JR sin enlace (R0) y destino no alineado
kernel:
    GETTID R1
    MOVI   R2, 2
    SHL    R3, R1, R2          ; desplazamiento en bytes
    MOVI   R4, 5

    JAL    R31, double         ; llamada directa
    STORE  R4, R3, 0xA00       ; 10

    ; JALR con enlace y desplazamiento: R5 = &base, destino = R5 + 4*(triple-base)
    JAL    R5, base
base:
    ADD    R4, R1, R0
    JALR   R31, R5, 19         ; triple esta 19 instrucciones despues de base
    STORE  R4, R3, 0xB00

    ; Rd = Ra: el enlace se escribe despues de leer el destino
    JAL    R6, here
here:
    JALR   R6, R6, 3           ; salta tres instrucciones mas alla de `here`
    MOVI   R7, 111             ; no se ejecuta
    MOVI   R7, 222             ; no se ejecuta
after:
    STORE  R6, R3, 0xC00

    ; JR sin enlace, con los dos bits bajos del destino sucios
    JAL    R8, target_base
target_base:
    ADDI   R8, R8, 23          ; target_base + 20 + 3 sucio: el destino es +20
    JR     R8
    MOVI   R9, 1               ; +8  no se ejecuta
    MOVI   R9, 2               ; +12 no se ejecuta
    MOVI   R9, 3               ; +16 no se ejecuta
    MOVI   R9, 4               ; +20 destino
    STORE  R9, R3, 0xD00
    HALT

double:
    ADD    R4, R4, R4
    JR     R31

triple:
    ADD    R10, R4, R4
    ADD    R4, R10, R4
    JR     R31
