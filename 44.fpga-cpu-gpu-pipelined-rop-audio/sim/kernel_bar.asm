; Kernel de prueba de barreras, divergencia y offset negativo (36).
; Cuatro warps de ocho lanes, tid = warp*8 + lane, un solo grupo.
;
;   A[tid] = tid + 100                       (0x800)
;   B[tid] = tid                             (0x900), con STORE de offset -4
;   D[tid] = tid + 1 si tid < 16, tid + 2 si no   (0xB00), tras una divergencia
;   BAR
;   C[tid] = A[tid + 8]                      (0xA00): lee lo que escribio OTRO warp
;
; Sin la barrera, el warp 0 leeria A[8..15] antes de que el warp 1 los escriba.
; B comprueba el sumador de direcciones: con un acarreo de mas entre lanes, la
; lane 1 escribiria un byte mas alla y el STORE seria un fallo de alineacion.

        GETTID R1
        MOVI   R3, 2
        SHL    R4, R1, R3
        LI     R5, 0x800
        ADD    R4, R4, R5          ; &A[tid]
        ADDI   R2, R1, 100
        STORE  R2, R4, 0           ; A[tid]
        ADDI   R6, R4, 0x104
        STORE  R1, R6, -4          ; B[tid] = &A + 0x100

        MOVI   R11, 16
        SSY    join
        BGE    R1, R11, high
        ADDI   R12, R1, 1
        BRA    join
high:
        ADDI   R12, R1, 2
        BRA    join
join:
        STORE  R12, R4, 0x300      ; D[tid]
        BAR
        ADDI   R10, R4, 32         ; &A[tid + 8]
        LOAD   R9, R10, 0
        STORE  R9, R4, 0x200       ; C[tid]
        EXIT
