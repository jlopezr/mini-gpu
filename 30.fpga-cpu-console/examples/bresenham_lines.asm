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
; R0 ESTA CABLEADO A CERO. Hasta la 19 era un registro general y este programa
; lo usaba para guardar la constante 5, con lo que hacia falta reservar OTRO
; registro (R3) solo para tener un cero con el que comparar. Ahora el cero es
; gratis, R3 esta libre y `JR Ra` es `JALR R0, Ra, 0`, con lo que el opcode
; 0x2E queda obsoleto. Ver docs/registro-cero.md.
;
; Las dos constantes que guardaban el sitio del rojo y del verde tampoco hacen
; falta: `SHLI` toma la cantidad del propio encoding, asi que `SHL R6, R6, R25`
; con R25 = 11 pasa a ser `SHLI R6, R6, 11` y se ahorra el registro y el MOVI.
; Ver docs/alu-extendida.md y la §1 del README.
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
;   R0  cero, cableado                  R1  base del buffer trasero
;   R2  base de los registros de video  R3  libre (era el cero)
;   R4  x de putpixel    R5  y de putpixel    R6  color
;   R7, R8  temporales de putpixel
;   R9  x0    R10 y0    R11 x1    R12 y1
;   R13 dx    R14 dy    R15 sx    R16 sy    R17 err   R18 e2
;   R19 parametro de borde (entrada de `edge`)
;   R20 parametro del extremo actual   R21 numero de recta
;   R22 giro acumulado del frame       R23 constante 1
;   R24 constante 640                  R25 libre (era el sitio del rojo)
;   R26 puntero de borrado             R27 fin de borrado
;   R28 temporal                       R29 temporal de `edge`
;   R30 enlace de putpixel             R31 enlace de drawline y de edge
; ============================================================

.include "mmio.inc"

start:
    LI    R2, MMIO_VIDEO_BASE

    ; Elegir donde vive el framebuffer. Tras el reset las dos bases valen
    ; cero --el framebuffer es una decision del programa, no una reserva
    ; que el hardware impone-- asi que heredarlas seria dibujar sobre el
    ; propio programa. La direccion es la de siempre; lo que cambia es que
    ; ahora hay que escribirla.
    MOVHI R30, 0x0100
    STORE R30, R2, MMIO_VIDEO_FB_FRONT_OFF          ; FB_FRONT
    MOVHI R30, 0x0102
    ORI   R30, R30, 0x5800
    STORE R30, R2, MMIO_VIDEO_FB_BACK_OFF          ; FB_BACK, un frame mas arriba

    ; Encender el scanout. Tras el reset el modo es PATTERN --la memoria
    ; recien encendida contiene basura, asi que arrancar leyendola daria
    ; una salida indefinida-- y un programa que dibuja tiene que pedir
    ; que se vea lo que dibuja. Ver video_registers.v, VIDEO_CTRL.
    MOVI  R30, 2               ; SCANOUT
    STORE R30, R2, MMIO_VIDEO_CTRL_OFF         ; VIDEO_CTRL
    MOVI  R23, 1
    MOVI  R24, 640
    MOVI  R22, 0               ; sin giro en el primer frame

frame:
    LOAD  R1, R2, MMIO_VIDEO_FB_BACK_OFF            ; R1 = FB_BACK; cambia en cada intercambio

    ; ---- borrar el buffer trasero ----
    ; Se compara el puntero contra el final con BLTU, sin contador aparte. Son
    ; direcciones, no numeros con signo, asi que la comparacion va sin signo.
    ADDI  R26, R1, 0
    MOVHI R27, 0x0002
    ORI   R27, R27, 0x5800     ; 320*240*2 = 153600 bytes
    ADD   R27, R27, R1
clear:
    STORE R0, R26, 0           ; fondo negro: cero sirve en las dos mitades
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
    SHLI  R6, R6, 11        ; el rojo empieza en el bit 11
    MOVI  R28, 63
    SUB   R28, R28, R21        ; verde6 = 63 - n, de 63 a 28
    SHLI  R28, R28, 5       ; el verde empieza en el bit 5
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
    STORE R23, R2, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R28, R2, MMIO_VIDEO_SWAP_OFF
    BNE   R28, R0, wait_swap

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

; Las dos rutinas viven ahora en x.tests/inc, en una sola copia. Estaban
; duplicadas aqui y en cube.asm; putpixel, ademas, en bresenham_circles.asm.
; El contrato es que R1 tenga la base del buffer trasero y R24 valga 640.
    .include "drawline.inc"     ; arrastra putpixel.inc, los dos con .once
