; ============================================================
; gpu_kernels.inc - kernels de sistema de la GPU: memset, memcpy, fill_rect y blit
;
; Ensamblador de GPU, en la misma imagen que la CPU (docs/diseno-gpu-dma.md §7).
; Cada kernel recibe SOLO el puntero al bloque de argumentos (GETARG):
;
;   +0 nwarps   +4 nlanes   +8 p0   +12 p1   +16 p2   ...
;
;   gpu_k_memset     p0 = dst   p1 = valor (ya replicado en la palabra)   p2 = nwords
;   gpu_k_memcpy     p0 = dst   p1 = src                                  p2 = nwords
;   gpu_k_fill_rect  p0 = dst (primera fila, alineado)   p1 = pitch (bytes)
;                    p2 = row_words   p3 = rows   p4 = valor (replicado)
;   gpu_k_blit       p0 = dst   p1 = dst_pitch   p2 = src   p3 = src_pitch
;                    p4 = row_words   p5 = rows
;
; Reparto estatico y sin coordinacion (§4.4). En memset y memcpy, la lane `l` del
; warp logico `w` recorre las palabras  w*nlanes + l,  y suma  nwarps*nlanes  cada
; vuelta. Lanes consecutivas tocan palabras consecutivas. Ningun warp espera a
; otro, asi que no hacen falta atomicas ni barreras.
;
; En fill_rect y blit, el warp `w` hace las filas w, w + nwarps, w + 2 nwarps...
; y, dentro de la fila, la lane `l` las palabras l, l + nlanes, l + 2 nlanes...
; Las ocho lanes de un warp siempre estan en la MISMA fila, asi que el bucle de
; filas no diverge y cada instruccion de memoria toca ocho palabras seguidas.
; Los pitch son en bytes y tienen que ser multiplos de 4, como las direcciones.
;
; La condicion del bucle de palabras DIVERGE en la ultima pasada (unas lanes ya han
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

; ---- fill_rect: R6 fila, R7 palabra, R15 inicio de la fila, R14 = 2 ----
gpu_k_fill_rect:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 4                      ; nlanes
    LOAD     R8, R1, 8                      ; dst
    LOAD     R9, R1, 12                     ; pitch
    LOAD     R10, R1, 16                    ; row_words
    LOAD     R11, R1, 20                    ; rows
    LOAD     R12, R1, 24                    ; valor
    MOVI     R14, 2
    ADDI     R6, R2, 0                      ; fila = warp logico
gpu_k_fill_rect_row:
    BGEU     R6, R11, gpu_k_fill_rect_end   ; la misma fila en las 8 lanes: no diverge
    MUL      R15, R6, R9
    ADD      R15, R15, R8                   ; inicio de la fila
    ADDI     R7, R3, 0                      ; palabra = lane
    SSY      gpu_k_fill_rect_next
gpu_k_fill_rect_col:
    BGEU     R7, R10, gpu_k_fill_rect_next
    SHL      R13, R7, R14
    ADD      R13, R13, R15
    STORE    R12, R13, 0
    ADD      R7, R7, R5
    BRA      gpu_k_fill_rect_col
gpu_k_fill_rect_next:
    ADD      R6, R6, R4
    BRA      gpu_k_fill_rect_row
gpu_k_fill_rect_end:
    EXIT

; ---- blit: R6 fila, R7 palabra, R15 inicio de la fila de dst, R16 la de src ----
gpu_k_blit:
    GETARG   R1
    GETLWARP R2
    GETLANE  R3
    LOAD     R4, R1, 0                      ; nwarps
    LOAD     R5, R1, 4                      ; nlanes
    LOAD     R8, R1, 8                      ; dst
    LOAD     R9, R1, 12                     ; dst_pitch
    LOAD     R10, R1, 16                    ; src
    LOAD     R11, R1, 20                    ; src_pitch
    LOAD     R12, R1, 24                    ; row_words
    LOAD     R13, R1, 28                    ; rows
    MOVI     R14, 2
    ADDI     R6, R2, 0                      ; fila = warp logico
gpu_k_blit_row:
    BGEU     R6, R13, gpu_k_blit_end
    MUL      R15, R6, R9
    ADD      R15, R15, R8                   ; fila de dst
    MUL      R16, R6, R11
    ADD      R16, R16, R10                  ; fila de src
    ADDI     R7, R3, 0
    SSY      gpu_k_blit_next
gpu_k_blit_col:
    BGEU     R7, R12, gpu_k_blit_next
    SHL      R17, R7, R14                   ; 4 * palabra
    ADD      R18, R17, R16
    LOAD     R19, R18, 0                    ; src
    ADD      R17, R17, R15
    STORE    R19, R17, 0                    ; dst
    ADD      R7, R7, R5
    BRA      gpu_k_blit_col
gpu_k_blit_next:
    ADD      R6, R6, R4
    BRA      gpu_k_blit_row
gpu_k_blit_end:
    EXIT
