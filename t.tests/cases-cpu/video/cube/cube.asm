; ============================================================
; cube.asm - cubo en alambre girando sobre dos ejes
;
; Ocho vertices, doce aristas, rotacion en X y en Y a velocidades distintas, y
; proyeccion en perspectiva. Las rectas las traza el mismo `drawline` de
; `bresenham_lines.asm`: el cubo no es un algoritmo de dibujo nuevo, es lo que
; se puede construir encima del que ya habia.
;
; Coma fija
; ---------
;
; Los vertices y las rotaciones van en Q16.16 con `MULFX`, que es exactamente
; la multiplicacion Q16.16 de la ISA: producto signed de 64 bits desplazado
; aritmeticamente 16 a la derecha. Nada de esto necesita coma flotante.
;
; La rotacion es la de siempre, primero en X y luego en Y:
;
;     y1 = y*cos a - z*sin a        z1 = y*sin a + z*cos a
;     x2 = x*cos b + z1*sin b       z2 = z1*cos b - x*sin b
;
; Los senos salen de una tabla de 256 entradas en Q16.16 (`.word`, o sea en la
; imagen del programa, no construida en tiempo de ejecucion). El coseno es la
; misma tabla desplazada 64 posiciones: cos t = sin(t + 90 grados). Una tabla,
; no dos.
;
; Proyeccion
; ----------
;
; Perspectiva de libro, con la camara a z = 3:
;
;     sx = 160 + (xi * 140) / zi        sy = 120 + (yi * 140) / zi
;
; Antes de dividir se baja de Q16.16 a enteros con `SARI 8`. No es por gusto:
; en Q16.16 el cociente de dos numeros del mismo orden sale cero, porque `DIV`
; es entera. Trabajando en unidades de 1/256 los numeradores quedan en unos
; pocos centenares y la division entera ya da pixeles utiles.
;
; La escala 140 no es arbitraria. Un vertice del cubo tiene norma sqrt(3), asi
; que una coordenada rotada llega a 1,732 y `zi` baja hasta 324. Con 140 el
; cubo se queda en x 61..259 e y 21..219, comprobado barriendo los 65 536 pares
; de angulos. Con 200 --el valor que probe primero-- se salia a 19..301.
;
; Borrado por caja
; ----------------
;
; No se borra la pantalla entera sino la caja [32,288) x [8,232), que es donde
; el cubo puede llegar. Son 28 672 palabras en vez de 38 400, y la diferencia
; es justo la que separa 60 fps de 30. Medido en la 21 comparando FRAME_COUNT
; (STATUS[31:16]) contra SWAP_COUNT, que cuentan cosas distintas:
;
;     borrado por caja    0,99 frames de video por intercambio   60 fps
;     borrado entero      2,00 frames de video por intercambio   30 fps
;
; El 2,00 clavado es lo que delata el mecanismo: no es que vaya "un poco mas
; lento", es que el dibujo no termina dentro del frame y el scanout repite el
; anterior entero. Esta CPU ejecuta unas 147 000 instrucciones por frame de
; video con esta mezcla de instrucciones --no es una constante de la maquina,
; depende de cuanto pare la memoria-- y el borrado entero no cabe ahi.
;
; Convencion de registros:
;   R0  cero, cableado                  R1  base del buffer trasero
;   R2  base de los registros de video  R3  puntero de tabla / de borrado
;   R4  x de putpixel   R5  y de putpixel   R6  color
;   R7, R8  temporales de putpixel y de la rotacion
;   R9  x0    R10 y0    R11 x1    R12 y1     (entrada de drawline)
;   R13 dx    R14 dy    R15 sx    R16 sy   R17 err   R18 e2   (drawline)
;   R19 contador de bucle               R20 sin a   R21 cos a
;   R22 sin b   R23 cos b               R24 constante 640
;   R25 constante 1                     R26 angulo a   R27 angulo b
;   R28, R29 temporales                 R30 enlace de putpixel
;   R31 enlace de drawline
; ============================================================

.include "mmio.inc"

start:
    LI    R2, MMIO_VIDEO_BASE

    MOVHI R28, 0x0100
    STORE R28, R2, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT = 0x01000000
    MOVHI R28, 0x0102
    ORI   R28, R28, 0x5800
    STORE R28, R2, MMIO_VIDEO_FB_BACK_OFF           ; FB_BACK  = 0x01025800

    MOVI  R28, 2               ; SCANOUT: tras el reset el modo es PATTERN
    STORE R28, R2, MMIO_VIDEO_CTRL_OFF          ; VIDEO_CTRL

    MOVI  R24, 640
    MOVI  R25, 1
    MOVI  R26, 0               ; angulo del eje X
    MOVI  R27, 0               ; angulo del eje Y

    ; El buffer delantero tambien hay que limpiarlo una vez: el borrado por
    ; caja no lo toca nunca, y la SDRAM recien encendida tiene basura que se
    ; quedaria fija alrededor del cubo para siempre.
    MOVHI R3, 0x0100
    MOVHI R28, 0x0104
    ORI   R28, R28, 0xB000     ; 0x01000000 + 2*153600, los dos buffers
clear_once:
    STORE R0, R3, 0
    ADDI  R3, R3, 4
    BLTU  R3, R28, clear_once

frame:
    LOAD  R1, R2, MMIO_VIDEO_FB_BACK_OFF            ; R1 = FB_BACK; cambia en cada intercambio

    ; ---- borrar solo la caja donde cabe el cubo ----
    MOVI  R28, 5184            ; 8 filas * 640 + 32 px * 2 bytes
    ADD   R3, R1, R28          ; esquina (32, 8)
    MOVI  R19, 224             ; filas de la caja
clear_row:
    ADDI  R28, R3, 0
    MOVI  R29, 128             ; 256 px = 128 palabras
clear_word:
    STORE R0, R28, 0
    ADDI  R28, R28, 4
    ADDI  R29, R29, -1
    BNE   R29, R0, clear_word
    ADD   R3, R3, R24
    ADDI  R19, R19, -1
    BNE   R19, R0, clear_row

    ; ---- senos y cosenos de los dos angulos ----
    ; cos t = sin(t + 64) sobre una tabla de 256 entradas: el +64 es el cuarto
    ; de vuelta. El AND 255 la cierra en anillo sin comparar nada.
    MOVI  R7, sin_table
    SHLI  R28, R26, 2
    ADD   R28, R7, R28
    LOAD  R20, R28, 0          ; sin a
    ADDI  R28, R26, 64
    ANDI  R28, R28, 255
    SHLI  R28, R28, 2
    ADD   R28, R7, R28
    LOAD  R21, R28, 0          ; cos a

    SHLI  R28, R27, 2
    ADD   R28, R7, R28
    LOAD  R22, R28, 0          ; sin b
    ADDI  R28, R27, 64
    ANDI  R28, R28, 255
    SHLI  R28, R28, 2
    ADD   R28, R7, R28
    LOAD  R23, R28, 0          ; cos b

    ; ---- rotar y proyectar los ocho vertices ----
    ; Se proyectan todos ANTES de trazar ninguna arista, y el resultado va a
    ; 0x00100000. Si se proyectara dentro del bucle de aristas, cada vertice se
    ; rotaria tres veces --cada uno toca tres aristas-- y son seis MULFX y una
    ; division cada vez.
    MOVI  R3, vertices
    MOVHI R29, 0x0010          ; tabla de puntos proyectados en 0x00100000
    MOVI  R19, 8
vertex_loop:
    LOAD  R4, R3, 0            ; x
    LOAD  R5, R3, 4            ; y
    LOAD  R6, R3, 8            ; z

    MULFX R7,  R5, R21         ; y*cos a
    MULFX R8,  R6, R20         ; z*sin a
    SUB   R7,  R7, R8          ; y1

    MULFX R8,  R5, R20         ; y*sin a
    MULFX R28, R6, R21         ; z*cos a
    ADD   R8,  R8, R28         ; z1

    MULFX R9,  R4, R23         ; x*cos b
    MULFX R28, R8, R22         ; z1*sin b
    ADD   R9,  R9, R28         ; x2

    MULFX R10, R8, R23         ; z1*cos b
    MULFX R28, R4, R22         ; x*sin b
    SUB   R10, R10, R28        ; z2

    SARI  R9,  R9, 8           ; a unidades de 1/256, ver cabecera
    SARI  R7,  R7, 8
    MOVHI R28, 0x0003          ; camara a z = 3.0 en Q16.16
    ADD   R10, R10, R28
    SARI  R10, R10, 8          ; zi, siempre > 0

    MOVI  R28, 140             ; escala de proyeccion
    MUL   R11, R9, R28
    DIV   R11, R11, R10
    ADDI  R11, R11, 160        ; sx
    MUL   R12, R7, R28
    DIV   R12, R12, R10
    ADDI  R12, R12, 120        ; sy

    STORE R11, R29, 0
    STORE R12, R29, 4

    ADDI  R3,  R3, 12
    ADDI  R29, R29, 8
    ADDI  R19, R19, -1
    BNE   R19, R0, vertex_loop

    ; ---- trazar las doce aristas ----
    ; La tabla guarda DESPLAZAMIENTOS en bytes, no indices: asi el bucle suma
    ; en vez de desplazar. Cada entrada lleva ademas su color, que es lo que
    ; hace legible el giro -- con un solo color el cubo se vuelve una maraña.
    MOVI  R3, edges
    MOVI  R19, 12
edge_loop:
    MOVHI R28, 0x0010
    LOAD  R29, R3, 0
    ADD   R29, R28, R29
    LOAD  R9,  R29, 0          ; x0
    LOAD  R10, R29, 4          ; y0
    LOAD  R29, R3, 4
    ADD   R29, R28, R29
    LOAD  R11, R29, 0          ; x1
    LOAD  R12, R29, 4          ; y1
    LOAD  R6,  R3, 8           ; color de la arista
    JAL   R31, drawline
    ADDI  R3,  R3, 12
    ADDI  R19, R19, -1
    BNE   R19, R0, edge_loop

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R25, R2, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R28, R2, MMIO_VIDEO_SWAP_OFF
    BNE   R28, R0, wait_swap

    ; Uno y tres: como 3 no divide a 256 ni comparte factores con 1, el par de
    ; angulos no vuelve a repetirse hasta dar la vuelta entera, y el cubo no
    ; cae nunca en un ciclo corto.
    ADDI  R26, R26, 1
    ANDI  R26, R26, 255
    ADDI  R27, R27, 3
    ANDI  R27, R27, 255
    BRA   frame
; Las rectas y los pixeles vienen de la biblioteca compartida. Estaban
; copiados aqui, identicos a los de bresenham_lines.asm y de
; bresenham_circles.asm; ahora hay una sola copia. El contrato es que R1
; tenga la base del buffer trasero y R24 valga 640, cosa que hace el
; bucle de arriba.
    .include "drawline.inc"     ; arrastra putpixel.inc, los dos con .once

    .rodata

; Los ocho vertices, (x, y, z) en Q16.16. 65536 es 1.0.
;   0(-,-,-) 1(+,-,-) 2(-,+,-) 3(+,+,-)
;   4(-,-,+) 5(+,-,+) 6(-,+,+) 7(+,+,+)
vertices:
    .word -65536, -65536, -65536
    .word  65536, -65536, -65536
    .word -65536,  65536, -65536
    .word  65536,  65536, -65536
    .word -65536, -65536,  65536
    .word  65536, -65536,  65536
    .word -65536,  65536,  65536
    .word  65536,  65536,  65536

; Doce aristas: desplazamiento en bytes del primer punto, del segundo, y color.
; Cada punto proyectado ocupa 8 bytes, asi que el vertice i esta en i*8.
; La cara z- va en cyan, la z+ en magenta y las cuatro uniones en blanco: con
; un solo color el cubo girando se lee como una maraña de lineas.
edges:
    .word  0,  8, 0x07FF
    .word  8, 24, 0x07FF
    .word 24, 16, 0x07FF
    .word 16,  0, 0x07FF
    .word 32, 40, 0xF81F
    .word 40, 56, 0xF81F
    .word 56, 48, 0xF81F
    .word 48, 32, 0xF81F
    .word  0, 32, 0xFFFF
    .word  8, 40, 0xFFFF
    .word 16, 48, 0xFFFF
    .word 24, 56, 0xFFFF
    .include "sin256.inc"
