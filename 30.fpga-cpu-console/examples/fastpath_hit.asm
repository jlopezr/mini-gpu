; Mide en la placa lo que ahorra el camino rapido de la 21. Mitad con ACIERTO.
;
; Va en pareja con fastpath_miss.asm, que es este mismo fichero con UN caracter
; distinto: el REM lee R3 en vez de R2.
;
;   hit:   DIV R5, R1, R2      miss:  DIV R5, R1, R2
;          REM R6, R1, R2             REM R6, R1, R3
;
; R2 y R3 valen los dos 3. El cociente es el mismo, el resto es el mismo y las
; instrucciones ejecutadas son exactamente las mismas: 4004 en los dos casos.
; Lo unico que cambia es el NUMERO de registro, y la etiqueta guarda numeros,
; no valores, asi que la segunda version falla y rehace la division entera.
;
; Montarlo asi --en vez de comparar contra una version con un NOP intercalado--
; evita tener que descontar el coste del NOP, que en la placa no son seis
; ciclos limpios sino lo que tarde el fetch. La resta de los dos contadores ES
; el ahorro, sin correcciones.
;
; Como se mide, desde el PC:
;
;   monitor.py reset; monitor.py write-block 0x0 fastpath_hit.bin
;   monitor.py run;   monitor.py perf
;
; y lo mismo con el otro. Los contadores 0x36/0x37 cuentan desde el reset, asi
; que hay que resetear entre las dos medidas.

    MOVI  R1, 30000            ; dividendo
    MOVI  R2, 3                ; divisor
    MOVI  R3, 3                ; el MISMO valor, en otro registro
    MOVI  R4, 1000             ; vueltas

bucle:
    DIV   R5, R1, R2
    REM   R6, R1, R2           ; acierta: misma pareja de registros
    ADDI  R4, R4, -1
    BNE   R4, R0, bucle

    HALT
