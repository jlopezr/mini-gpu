; Un acceso de 8 bits a MMIO es un error, no se trunca ni se parte (mmio.md 4.1).
;
; Los registros de dispositivo son de palabras completas. La palabra entera de
; SYSTEM se lee sin problema (existe en toda GPU); el byte del mismo registro,
; no. Y el error NO deja escrito nada: aqui no hay nada que ver, pero en una
; escritura (STOREB, STOREH) un fallo que aun asi llegara al bus escribiria el
; registro entero.
.include "mmio.inc"
    LI    R1, MMIO_SYSTEM_BASE  ; 0x00 y 0x04: LI de 32 bits ocupa dos palabras
    LOAD  R2, R1, 0             ; 0x08: SYSTEM_ID, de palabra: legal
    LOADB R3, R1, 0             ; 0x0C: de byte, al mismo registro: error
    HALT
