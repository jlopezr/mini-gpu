; Comprueba que la GPU alcanza la ventana MMIO por si misma, que es lo que
; antes era imposible: la LSU marcaba fault todo lo que pasara de 0x02000000 y
; ademas el MMIO exigia `halted`, o sea que solo lo tocaba el host.
;
; Solo el hilo 0 toca el MMIO. Los accesos a MMIO son ESCALARES (una lane cada
; vez), asi que dejar que los 64 hilos escriban el mismo registro seria correcto
; pero absurdo: 64 accesos serializados para el mismo valor.
;
; OJO con dos cosas de esta ISA:
;   - un salto DIVERGENTE necesita `SSY etiqueta` delante, marcando donde
;     reconvergen los caminos. Sin el, el SM para con ERROR_SIMT (0x06).
;   - el inmediato de LOAD/STORE es un desplazamiento en BYTES, no en palabras:
;     `mem32[Ra + imm]`. De ahi el 512 para 0x200 y no 128.
;
; Deja en registros del hilo 0, para que el banco y el monitor los lean:
;   R10 = VIDEO_CTRL leido de vuelta
;   R11 = ciclos consumidos por el bucle de trabajo
;   R12 = instrucciones retiradas en ese mismo tramo
;
; Que la GPU pueda leer CYCLES es la mitad del objetivo de instrumentar: un
; programa se cronometra a si mismo en la placa, sin simular y sin UART.

        GETTID R1
        MOVHI R20, 0x8000       ; R20 = 0x80000000, base del MMIO

        SSY   after_mmio
        BNE   R1, R0, after_mmio   ; los que no son el hilo 0 se saltan esto
        MOVI  R2, 2                ; VIDEO_CTRL = SCANOUT
        STORE R2, R20, 512         ; 0x80000200
        LOAD  R10, R20, 512        ; releer: deberia dar 2
        LOAD  R3, R20, 768         ; 0x80000300 CYCLES
        LOAD  R4, R20, 772         ; 0x80000304 RETIRED
after_mmio:
        BAR

        ; --- trabajo a medir: memoria coalescida mas algo de ALU ---
        MOVI  R5, 64
        MOVI  R6, 4
        MUL   R7, R1, R6
        ADDI  R7, R7, 4096      ; base + tid*4
        MOVI  R8, 0
work:
        LOAD  R9, R7, 0
        ADD   R8, R8, R9
        STORE R8, R7, 0
        ADDI  R5, R5, -1
        BNE   R5, R0, work      ; no diverge: R5 es igual en todas las lanes

        BAR

        SSY   done
        BNE   R1, R0, done
        LOAD  R11, R20, 768     ; CYCLES otra vez
        SUB   R11, R11, R3      ; ciclos del tramo
        LOAD  R12, R20, 772     ; RETIRED otra vez
        SUB   R12, R12, R4      ; instrucciones del tramo
done:
        BAR
        HALT
