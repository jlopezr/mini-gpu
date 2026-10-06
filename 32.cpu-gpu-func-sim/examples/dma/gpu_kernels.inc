; ============================================================
; gpu_kernels.inc - kernels de sistema de la GPU: memset y memcpy
;
; Ensamblador de GPU, en la misma imagen que la CPU (docs/diseno-gpu-dma.md §7).
; Cada kernel recibe SOLO el puntero al bloque de argumentos (GETARG):
;
;   +0 nwarps   +4 nlanes   +8 p0   +12 p1   +16 p2   ...
;
;   gpu_k_memset   p0 = dst    p1 = valor (ya replicado en la palabra)   p2 = nwords
;   gpu_k_memcpy   p0 = dst    p1 = src                                  p2 = nwords
;
; Reparto estatico y sin coordinacion (§4.4): la lane `l` del warp logico `w`
; recorre las palabras  w*nlanes + l,  y suma  nwarps*nlanes  cada vuelta. Lanes consecutivas tocan palabras consecutivas. Ningun warp espera a
; otro, asi que no hacen falta atomicas ni barreras.
;
; La condicion del bucle DIVERGE en la ultima pasada (unas lanes ya han
; terminado, otras no): un salto divergente sin SSY detiene la GPU con
; ERROR_SIMT. Por eso el SSY va delante del bucle y apunta a la salida.
;
; Registros de GPU: no hay SHLI, el *4 va con un SHL por registro (R11 = 2).
; ============================================================

gpu_k_memset:
    GETARG   R1                             ; bloque de argumentos
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 4                      ; nlanes
    MUL      R6, R2, R5
    ADD      R6, R6, R3                     ; i = lwarp * nlanes + lane
    MUL      R7, R4, R5                     ; paso = nwarps * nlanes
    LOAD     R8, R1, 8                      ; dst
    LOAD     R9, R1, 12                     ; valor
    LOAD     R10, R1, 16                    ; nwords
    MOVI     R11, 2
    SSY      gpu_k_memset_end
gpu_k_memset_loop:
    BGEU     R6, R10, gpu_k_memset_end
    SHL      R12, R6, R11
    ADD      R12, R12, R8                   ; &dst[i]
    STORE    R9, R12, 0
    ADD      R6, R6, R7
    BRA      gpu_k_memset_loop
gpu_k_memset_end:
    EXIT

gpu_k_memcpy:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 4                      ; nlanes
    MUL      R6, R2, R5
    ADD      R6, R6, R3                     ; i
    MUL      R7, R4, R5                     ; paso
    LOAD     R8, R1, 8                      ; dst
    LOAD     R9, R1, 12                     ; src
    LOAD     R10, R1, 16                    ; nwords
    MOVI     R11, 2
    SSY      gpu_k_memcpy_end
gpu_k_memcpy_loop:
    BGEU     R6, R10, gpu_k_memcpy_end
    SHL      R12, R6, R11                   ; 4 * i
    ADD      R13, R12, R9
    LOAD     R14, R13, 0                    ; src[i]
    ADD      R12, R12, R8
    STORE    R14, R12, 0                    ; dst[i]
    ADD      R6, R6, R7
    BRA      gpu_k_memcpy_loop
gpu_k_memcpy_end:
    EXIT
