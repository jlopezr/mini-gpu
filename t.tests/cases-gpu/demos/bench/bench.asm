; Nucleo de medida para comparar 22 (BL8 + bufer + LSU v2) contra 17 (BL1).
;
; Esta hecho para medir el CAMINO DE MEMORIA, que es lo que cambia entre los
; dos, no la ALU:
;
;   - Direcciones lane*4 + base: las 8 lanes caen en dos lineas de 16 bytes
;     consecutivas, o sea el caso COALESCIDO. En 17 eso son 8 accesos de lane
;     con dos BL1 cada uno; en 22 son 2 transacciones BL8.
;   - Un LOAD y un STORE por iteracion, para mover trafico de datos de verdad.
;   - El bucle son 5 instrucciones = 20 bytes, o sea 2 lineas de 16 bytes:
;     entra de sobra en las 4 lineas del bufer de instrucciones, asi que el
;     fetch acierta casi siempre y no domina la medida.
;
; Los 32 casos diferenciales NO sirven para esto: son pruebas de ISA, con
; programas cortos y casi nada de trafico de datos. De ahi que su medida
; estuviera dominada por el fetch.
;
; R5 es el contador de iteraciones. Subirlo alarga la prueba de forma lineal.
        GETTID R1
        MOVI  R2, 4
        MUL   R3, R1, R2
        ADDI  R3, R3, 4096      ; base de datos + lane*4
        MOVI  R4, 0             ; acumulador
        MOVI  R5, 2000          ; iteraciones
        MOVI  R6, 1
loop:
        LOAD  R7, R3, 0
        ADD   R4, R4, R7
        STORE R4, R3, 0
        SUB   R5, R5, R6
        BNE   R5, R0, loop
        BAR
        HALT
