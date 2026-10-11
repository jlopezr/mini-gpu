; ============================================================
; putpixel.inc - un pixel RGB565 en el buffer trasero
;
; Contrato con quien lo incluye: NO es autonomo, depende de dos registros que
; el programa tiene que dejar puestos.
;
;   R1   base del buffer trasero
;   R24  constante 640, la zancada de linea en bytes
;
; No se inicializan aqui a proposito. R1 cambia en cada intercambio y solo el
; programa sabe cuando releerlo; y poner R24 en cada llamada seria una
; instruccion por pixel.
;
; Etiqueta reservada: putpixel.
; ============================================================

    .once

; ------------------------------------------------------------
; putpixel: escribe el pixel (R4, R5) del color R6 en el buffer trasero.
;
; direccion = base + y*640 + x*2. Se usa MUL para el y*640: son 11 ciclos,
; frente a los 37 que costarian los dos SHL iterativos y la suma que usan las
; demos heredadas de la 18. El x*2 se hace sumando, que son 7.
;
; No comprueba limites. Quien lo llama es responsable de que el punto caiga
; dentro: en el abanico y las circunferencias porque no salen de su caja, y en
; el cubo porque el rango de la proyeccion esta acotado y comprobado.
;
; Deja la direccion en R7, que para el borrado incremental no es un efecto
; colateral sino parte del contrato.
;
; Entrada: R4, R5, R6. No los modifica. Salida: R7. Usa R8. Vuelve por R30.
; ------------------------------------------------------------
putpixel:
    MUL    R7, R5, R24         ; y * 640
    ADD    R8, R4, R4          ; x * 2
    ADD    R7, R7, R8
    ADD    R7, R7, R1
    STOREH R6, R7, 0           ; un pixel, dos bytes, sin leer nada antes
    JR     R30

