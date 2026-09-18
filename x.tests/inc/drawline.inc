; ============================================================
; drawline.inc - trazado de rectas por Bresenham
;
; Estaba copiado literalmente en bresenham_lines.asm y en cube.asm, que es
; parte del motivo de que exista `.include`: una correccion habia que hacerla
; dos veces, con el riesgo de que los casos de x.tests que comparan contra el
; abanico pasaran mientras el cubo se quedaba con la version vieja.
;
; DEPENDE de `putpixel.inc`, y lo incluye el solo: los dos llevan `.once`, asi
; que el programa puede incluir tambien putpixel.inc --o no-- y entra una sola
; vez igualmente. bresenham_circles.asm sigue pudiendo pedir putpixel sin
; drawline, que es el caso que obliga a que sean dos ficheros y no uno.
;
; Etiquetas reservadas: drawline, dx_ready, dy_positive, dy_ready, line_step,
; advance, skip_x, skip_y, line_done.
;
; Solo define una rutina; no emite nada que se ejecute por caer dentro.
; Incluyelo DESPUES del bucle principal, o saltalo.
; ============================================================

    .once

; ------------------------------------------------------------
; drawline: traza la recta de (R9,R10) a (R11,R12) con el color R6.
;
; Bresenham entero en su forma de los ocho octantes. En vez de calcular y para
; cada x, se lleva un termino de error que dice cuanto se ha desviado la recta
; ideal del pixel recien pintado, y se avanza en x, en y o en las dos segun su
; signo. Todo son sumas.
;
; `dy` se guarda NEGADO a proposito. Asi las dos decisiones del bucle son
; `e2 >= dy` y `e2 <= dx` --simetricas, sin valores absolutos ni casos
; especiales-- y la misma rutina vale para las rectas horizontales, las
; verticales y las diagonales sin comprobarlas aparte.
;
; Entrada: R9, R10, R11, R12 y R6.
; Destruye R9, R10 y R13..R18, ademas de lo de putpixel. Vuelve por R31.
; ------------------------------------------------------------
drawline:
    SUB   R13, R11, R9         ; dx = x1 - x0
    MOVI  R15, 1               ; sx = +1
    BGE   R13, R0, dx_ready
    SUB   R13, R0, R13         ; dx = |dx|
    MOVI  R15, -1

dx_ready:
    SUB   R14, R12, R10        ; dy = y1 - y0
    MOVI  R16, 1               ; sy = +1
    BGE   R14, R0, dy_positive
    MOVI  R16, -1              ; si ya es negativo, ya vale -|dy|
    BRA   dy_ready
dy_positive:
    SUB   R14, R0, R14         ; dy = -|dy|

dy_ready:
    ADD   R17, R13, R14        ; err = dx + dy

line_step:
    ADDI  R4, R9, 0
    ADDI  R5, R10, 0
    JAL   R30, putpixel

    BNE   R9, R11, advance     ; ¿ya se llego al extremo?
    BEQ   R10, R12, line_done

advance:
    ADD   R18, R17, R17        ; e2 = 2*err
    BLT   R18, R14, skip_x     ; si e2 >= dy, avanzar en x
    ADD   R17, R17, R14
    ADD   R9, R9, R15
skip_x:
    BLT   R13, R18, skip_y     ; si e2 <= dx, avanzar en y
    ADD   R17, R17, R13
    ADD   R10, R10, R16
skip_y:
    BRA   line_step

line_done:
    RET                        ; alias de JR R31



    .include "putpixel.inc"
