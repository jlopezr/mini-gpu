; ============================================================
; bresenham_lines.asm - abanico de rectas por el algoritmo de Bresenham
;
; Treinta y seis rectas desde el centro de la pantalla hasta puntos repartidos
; por el borde, girando un poco en cada frame. El reparto no es decorativo: los
; puntos del borde caen en los OCHO octantes, asi que el abanico recorre todos
; los casos del algoritmo --pendiente mayor y menor que uno, en las cuatro
; combinaciones de signo-- en cada frame. Una implementacion que solo valga
; para el primer octante se ve mal a simple vista.
;
; Por que Bresenham y no y = mx + b: esta CPU no tiene coma flotante ni
; division rapida --DIV cuesta 40 ciclos, ver docs/cycles.md--. Bresenham
; decide el pixel siguiente con sumas y una comparacion de enteros, que es
; justo lo que esta maquina hace barato.
;
; ---- Lo que este programa ensena de las llamadas ----
;
; Es el primer ejemplo que usa JAL/JALR/JR. `putpixel` como subrutina no es un
; capricho: sin llamadas habria que repetir su cuerpo en cada sitio que pinta,
; o saltar con BRA y volver a una etiqueta fija, que solo funciona si se llama
; desde un unico sitio.
;
; Hay dos niveles de llamada --main -> drawline -> putpixel-- y el enlace vive
; en un REGISTRO, asi que el segundo nivel machacaria el primero. Aqui se
; resuelve con dos registros de enlace distintos: R31 para drawline y R30 para
; putpixel. Funciona porque JAL nombra su registro de enlace explicitamente,
; que es exactamente para lo que la ISA lo dejo explicito en vez de fijarlo.
;
; **Esto no escala.** Con tres o cuatro niveles se acaban los registros, y con
; recursion no vale ni con uno. La solucion de verdad es una pila: salvar R31
; en memoria al entrar y restaurarlo al salir, como hace el caso
; `calls-link-and-return` de x.cpu-tests. Con dos niveles, dos registros son
; mas baratos y mas claros. Ver docs/llamadas.md.
;
; ---- Detalles de esta maquina ----
;
; R0 ES UN REGISTRO GENERAL. No esta cableado a cero, asi que aqui se usa como
; cualquier otro --guarda la constante 5-- y hace falta reservar otro registro
; (R3) para tener un cero con el que comparar. Esa es la razon de que JR tenga
; opcode propio en vez de ser `JALR R0, Ra, 0` como en RISC-V.
;
; El framebuffer es RGB565: 320x240 pixeles de dos bytes, 640 bytes por linea.
; Un pixel es un STOREH, sin leer nada antes; con solo STORE de 32 bits cada
; pixel costaria una lectura y una mezcla. Ver docs/accesos-sub-palabra.md.
;
; RGB565:  bits 15:11 rojo   bits 10:5 verde   bits 4:0 azul
;
; Registros de video, en 0x80000000:
;   +0  FB_FRONT   +4  FB_BACK   +8  SWAP   +12  STATUS
;
; Convencion de registros:
;   R0  constante 5 (sitio del verde)   R1  base del buffer trasero
;   R2  base de los registros de video  R3  constante 0
;   R4  x de putpixel    R5  y de putpixel    R6  color
;   R7, R8  temporales de putpixel
;   R9  x0    R10 y0    R11 x1    R12 y1
;   R13 dx    R14 dy    R15 sx    R16 sy    R17 err   R18 e2
;   R19 parametro de borde (entrada de `edge`)
;   R20 parametro del extremo actual   R21 numero de recta
;   R22 giro acumulado del frame       R23 constante 1
;   R24 constante 640                  R25 constante 11 (sitio del rojo)
;   R26 puntero de borrado             R27 fin de borrado
;   R28 temporal                       R29 temporal de `edge`
;   R30 enlace de putpixel             R31 enlace de drawline y de edge
; ============================================================

start:
    MOVHI R2, 0x8000           ; registros de video en 0x80000000

    ; Elegir donde vive el framebuffer. Tras el reset las dos bases valen
    ; cero --el framebuffer es una decision del programa, no una reserva
    ; que el hardware impone-- asi que heredarlas seria dibujar sobre el
    ; propio programa. La direccion es la de siempre; lo que cambia es que
    ; ahora hay que escribirla.
    MOVHI R30, 0x0100
    STORE R30, R2, 0          ; FB_FRONT
    MOVHI R30, 0x0102
    ORI   R30, R30, 0x5800
    STORE R30, R2, 4          ; FB_BACK, un frame mas arriba

    ; Encender el scanout. Tras el reset el modo es PATTERN --la memoria
    ; recien encendida contiene basura, asi que arrancar leyendola daria
    ; una salida indefinida-- y un programa que dibuja tiene que pedir
    ; que se vea lo que dibuja. Ver video_registers.v, VIDEO_CTRL.
    MOVI  R30, 2               ; SCANOUT
    STORE R30, R2, 24         ; VIDEO_CTRL
    MOVI  R3, 0                ; el cero con el que se compara; R0 no lo es
    MOVI  R0, 5
    MOVI  R23, 1
    MOVI  R24, 640
    MOVI  R25, 11
    MOVI  R22, 0               ; sin giro en el primer frame

frame:
    LOAD  R1, R2, 4            ; R1 = FB_BACK; cambia en cada intercambio

    ; ---- borrar el buffer trasero ----
    ; Se compara el puntero contra el final con BLTU, sin contador aparte. Son
    ; direcciones, no numeros con signo, asi que la comparacion va sin signo.
    ADDI  R26, R1, 0
    MOVHI R27, 0x0002
    ORI   R27, R27, 0x5800     ; 320*240*2 = 153600 bytes
    ADD   R27, R27, R1
clear:
    STORE R3, R26, 0           ; fondo negro: cero sirve en las dos mitades
    ADDI  R26, R26, 4
    BLTU  R26, R27, clear

    ; ---- el abanico ----
    MOVI  R21, 0
    ADDI  R20, R22, 0          ; el primer extremo sale del giro del frame

next_line:
    ; Color: el rojo crece con el numero de recta y el verde decrece, asi que
    ; el abanico va de verde a rojo. Se calcula una vez por recta, de modo que
    ; los SHL iterativos de esta CPU no se notan.
    SHR   R6, R21, R23         ; rojo5 = n/2, de 0 a 17
    SHL   R6, R6, R25
    MOVI  R28, 63
    SUB   R28, R28, R21        ; verde6 = 63 - n, de 63 a 28
    SHL   R28, R28, R0
    OR    R6, R6, R28
    ORI   R6, R6, 15           ; un fondo de azul para que el verde no se apague

    ADDI  R19, R20, 0
    JAL   R31, edge            ; extremo -> (R11, R12)
    MOVI  R9, 160              ; siempre desde el centro
    MOVI  R10, 120
    JAL   R31, drawline

    ; 36 rectas x 31 de paso son 1116 justos, o sea una vuelta exacta al
    ; perimetro: las rectas quedan repartidas y sin repetirse.
    ADDI  R20, R20, 31
    MOVI  R28, 1116
    BLT   R20, R28, no_wrap
    SUB   R20, R20, R28
no_wrap:
    ADDI  R21, R21, 1
    MOVI  R28, 36
    BLT   R21, R28, next_line

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R23, R2, 8           ; SWAP = 1
wait_swap:
    LOAD  R28, R2, 8
    BNE   R28, R3, wait_swap

    ; Girar el abanico. Siete no divide a 1116, asi que el dibujo no se repite
    ; hasta dar la vuelta entera.
    ADDI  R22, R22, 7
    MOVI  R28, 1116
    BLT   R22, R28, frame
    SUB   R22, R22, R28
    BRA   frame

; ------------------------------------------------------------
; edge: convierte el parametro R19 en un punto del borde, (R11, R12).
;
; El borde se recorre en sentido horario desde la esquina superior izquierda,
; y son 1116 pasos: 320 arriba, 239 a la derecha, 319 abajo y 238 a la
; izquierda. Cada tramo se resuelve con una resta, sin tablas ni division.
;
; Entrada: R19, entre 0 y 1115.   Salida: R11, R12.   Usa R29. Vuelve por R31.
; ------------------------------------------------------------
edge:
    MOVI  R29, 320
    BLT   R19, R29, edge_top
    MOVI  R29, 559
    BLT   R19, R29, edge_right
    MOVI  R29, 878
    BLT   R19, R29, edge_bottom

    MOVI  R11, 0               ; borde izquierdo, subiendo
    MOVI  R29, 1116
    SUB   R12, R29, R19        ; y de 238 a 1
    RET

edge_top:
    ADDI  R11, R19, 0          ; x de 0 a 319
    MOVI  R12, 0
    RET

edge_right:
    MOVI  R11, 319
    ADDI  R12, R19, -319       ; y de 1 a 239
    RET

edge_bottom:
    MOVI  R29, 877
    SUB   R11, R29, R19        ; x de 318 a 0
    MOVI  R12, 239
    RET

; ------------------------------------------------------------
; drawline: traza la recta de (R9,R10) a (R11,R12) con el color R6.
;
; Bresenham entero en su forma de los ocho octantes. La idea: en vez de
; calcular y para cada x, se lleva un termino de error que dice cuanto se ha
; desviado la recta ideal del pixel que se acaba de pintar, y se avanza en x,
; en y o en las dos segun el signo de ese error. Todo son sumas.
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
    BGE   R13, R3, dx_ready
    SUB   R13, R3, R13         ; dx = |dx|
    MOVI  R15, -1

dx_ready:
    SUB   R14, R12, R10        ; dy = y1 - y0
    MOVI  R16, 1               ; sy = +1
    BGE   R14, R3, dy_positive
    MOVI  R16, -1              ; si ya es negativo, ya vale -|dy|
    BRA   dy_ready
dy_positive:
    SUB   R14, R3, R14         ; dy = -|dy|

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

; ------------------------------------------------------------
; putpixel: escribe el pixel (R4, R5) del color R6 en el buffer trasero.
;
; direccion = base + y*640 + x*2. Se usa MUL para el y*640: son 11 ciclos,
; frente a los 37 que costarian los dos SHL iterativos y la suma que usan las
; demos heredadas de la 18. El x*2 se hace sumando, que son 7.
;
; No comprueba limites: todos los puntos que le llegan salen del borde de la
; pantalla o del centro, y Bresenham no se sale de la caja que forman.
;
; Entrada: R4, R5, R6. No los modifica. Usa R7 y R8. Vuelve por R30.
; ------------------------------------------------------------
putpixel:
    MUL    R7, R5, R24         ; y * 640
    ADD    R8, R4, R4          ; x * 2
    ADD    R7, R7, R8
    ADD    R7, R7, R1
    STOREH R6, R7, 0           ; un pixel, dos bytes, sin leer nada antes
    JR     R30
