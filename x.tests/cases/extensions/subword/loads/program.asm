; Las seis cargas sub-palabra sobre la misma palabra, 0xBEEFAA78.
;
; Cada tamaño se lee dos veces, con y sin signo, y en una posición donde el bit
; alto vale uno y en otra donde vale cero. Así ninguna pareja de opcodes puede
; pasar el caso por coincidencia.
;
; La memoria es little-endian: el byte 0 de la palabra es 0x78 y el 3 es 0xBE.

        MOVHI  R1, 0x0010
        ADDI   R1, R1, 0x0400     ; 0x00100400

        LOADUB R2, R1, 1          ; 0xAA con ceros   -> 0x000000AA
        LOADB  R3, R1, 1          ; 0xAA con signo   -> 0xFFFFFFAA
        LOADUB R4, R1, 0          ; 0x78, bit alto a cero: da igual el signo
        LOADB  R5, R1, 0          ; -> 0x00000078 los dos

        LOADUH R6, R1, 2          ; 0xBEEF con ceros -> 0x0000BEEF
        LOADH  R7, R1, 2          ; 0xBEEF con signo -> 0xFFFFBEEF
        LOADUH R8, R1, 0          ; 0xAA78 con ceros -> 0x0000AA78
        LOADH  R9, R1, 0          ; 0xAA78 con signo -> 0xFFFFAA78

        LOAD   R10, R1, 0         ; la palabra entera, sin extender nada
        LOADUB R11, R1, 3         ; dirección impar de byte: es legal

        HALT
