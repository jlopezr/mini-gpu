; Grupo 0 (pc 0)
        MOVI   R5, 4096
        BAR
        MOVI   R3, 7
        STORE  R3, R5, 0
        EXIT

; Grupo 1 (pc 20): espera la bandera del grupo 0 antes de su propia BAR.
; Un LOAD de warp son ocho lecturas en olas distintas: si el STORE del grupo 0 cae en medio,
; unos carriles ven 0 y otros 7. Por eso la espera va en una region SSY: la divergencia es legal,
; los carriles que ya vieron la bandera esperan en `done` y el warp reconverge entero antes de la
; BAR, pase lo que pase en el reparto de olas.
        MOVI   R5, 4096
wait:
        LOAD   R6, R5, 0
        SSY    done
        BNE    R6, R0, done
        BRA    wait
done:
        BAR
        MOVI   R4, 9
        EXIT
