; ============================================================
; starfield.asm - campo de estrellas con acercamiento, rollo demo
;
; 256 estrellas en un espacio 3D, proyectadas en perspectiva sobre 320x240.
; Cada frame acerca todas las estrellas un paso; las que pasan de largo
; reaparecen al fondo. El efecto es el tunel de estrellas de toda la vida.
;
; La perspectiva
; --------------
;
; Cada estrella es (x, y, z) con x,y en [-32768, 32767] y z en [Z_MIN, Z_MAX].
; La proyeccion es la division de siempre:
;
;     sx = 160 + x/z        sy = 120 + y/z
;
; Con z grande el cociente es pequeño y la estrella cae cerca del centro; segun
; z baja, se abre hacia los bordes cada vez mas deprisa. Esa aceleracion no hay
; que programarla: es la division. Por eso el ejemplo vive en la 21 y no en la
; 18 o la 19 -- necesita `DIV`, que es la capacidad `mul_div`.
;
; De donde salen las estrellas
; ----------------------------
;
; Del mismo xorshift32 de `x.tests/cases/programs/xorshift`:
;
;     x ^= x << 13;  x ^= x >> 17;  x ^= x << 5
;
; Aqui se le pide justo lo que un PRNG de demo tiene que dar: posiciones que no
; se repitan y que no formen patron visible. Tres detalles del uso:
;
;   - Las coordenadas salen de los 16 bits ALTOS con un solo `SARI 16`, que de
;     paso extiende el signo. En xorshift32 los bits bajos son de peor
;     calidad que los altos, y en un campo de estrellas un bit bajo malo se ve:
;     sale una rejilla.
;   - La z de arranque si usa los bits bajos con ANDI, pero solo para repartir
;     las estrellas en profundidad al empezar. Un sesgo ahi no se nota.
;   - Al reaparecer, la z NO es aleatoria: es Z_MAX siempre. Con z aleatoria la
;     estrella se materializaria a media distancia, o sea un pixel que aparece
;     de la nada en mitad de la pantalla. Naciendo al fondo entra pequeña, lenta
;     y oscura, que es lo que hace que parezca que uno avanza.
;
; La semilla no puede ser cero: xorshift se queda clavado en el cero.
;
; Brillo por profundidad
; ----------------------
;
; Tres niveles de gris RGB565 segun z. Es lo que da sensacion de volumen: sin
; ello el campo parece confeti plano. Los cortes (400 y 800) reparten el rango
; en tres tramos aproximadamente iguales.
;
; Coste
; -----
;
; Lo caro no son las estrellas --256 por dos divisiones son unos 20 000 ciclos--
; sino borrar el buffer entero: 38 400 palabras. Se borra entero a proposito,
; por lo mismo que `bounce.asm`: con doble buffer, borrar solo donde estaba cada
; estrella obliga a recordar la posicion anterior EN CADA BUFFER POR SEPARADO,
; porque el trasero no contiene el frame pasado sino el anterior a ese. Repintar
; entero hace que cualquier frame sea correcto por si mismo.
;
; Convencion de registros:
;   R0  cero, cableado                  R1  base del buffer trasero
;   R2  base de los registros de video  R3  puntero a la estrella actual
;   R4  x de putpixel    R5  y de putpixel    R6  color
;   R7, R8  temporales de putpixel
;   R9  x de la estrella   R10 y de la estrella   R11 z de la estrella
;   R12 contador de estrellas           R13 estado del xorshift
;   R14 constante 13   R15 constante 17   R16 constante 5   (desplazamientos)
;   R17 salida del xorshift             R18 Z_MIN   R19 Z_MAX
;   R20 numero de estrellas             R21 paso de acercamiento
;   R22 constante 320                   R23 constante 240
;   R24 constante 640                   R25 constante 1
;   R26 puntero de borrado              R27 fin de borrado
;   R28 temporal / z de entrada a `spawn`
;   R29 enlace de spawn                 R30 enlace de putpixel
;   R31 enlace de rnd
; ============================================================

.include "mmio.inc"

start:
    LI    R2, MMIO_VIDEO_BASE

    ; Framebuffer. Tras el reset las dos bases valen cero, asi que heredarlas
    ; seria dibujar sobre el propio programa: hay que escribirlas.
    MOVHI R28, 0x0100
    STORE R28, R2, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT = 0x01000000
    MOVHI R28, 0x0102
    ORI   R28, R28, 0x5800
    STORE R28, R2, MMIO_VIDEO_FB_BACK_OFF           ; FB_BACK  = 0x01025800, un frame mas arriba

    MOVI  R28, 2               ; SCANOUT: tras el reset el modo es PATTERN
    STORE R28, R2, MMIO_VIDEO_CTRL_OFF          ; VIDEO_CTRL

    MOVI  R14, 13              ; los tres desplazamientos del xorshift
    MOVI  R15, 17
    MOVI  R16, 5
    MOVHI R13, 0x1234          ; semilla = 0x12345678, distinta de cero
    ORI   R13, R13, 0x5678

    MOVI  R18, 128             ; Z_MIN: mas cerca que esto, la estrella pasa
    MOVI  R19, 1151            ; Z_MAX: el fondo
    MOVI  R20, 256             ; estrellas
    MOVI  R21, 6               ; paso de acercamiento, en unidades de z
    MOVI  R22, 320
    MOVI  R23, 240
    MOVI  R24, 640
    MOVI  R25, 1

    ; ---- sembrar el campo ----
    ; Aqui la z SI es aleatoria: al arrancar el campo tiene que estar ya
    ; poblado a todas las profundidades. Si todas nacieran en Z_MAX, el primer
    ; par de segundos no se veria nada.
    MOVHI R3, 0x0010           ; tabla de estrellas en 0x00100000
    MOVI  R12, 0
seed_loop:
    JAL   R31, rnd
    ANDI  R28, R17, 1023
    ADD   R28, R28, R18        ; z = Z_MIN + (0..1023)
    JAL   R29, spawn
    ADDI  R3, R3, 12
    ADDI  R12, R12, 1
    BLT   R12, R20, seed_loop

frame:
    LOAD  R1, R2, MMIO_VIDEO_FB_BACK_OFF            ; R1 = FB_BACK; cambia en cada intercambio

    ; ---- borrar el buffer trasero a negro ----
    ; Se compara el puntero contra el final con BLTU: son direcciones, no
    ; numeros con signo.
    ADDI  R26, R1, 0
    MOVHI R27, 0x0002
    ORI   R27, R27, 0x5800     ; 320*240*2 = 153600 bytes
    ADD   R27, R27, R1
clear:
    STORE R0, R26, 0           ; el cero sirve para los dos pixeles de la palabra
    ADDI  R26, R26, 4
    BLTU  R26, R27, clear

    ; ---- acercar y dibujar cada estrella ----
    MOVHI R3, 0x0010
    MOVI  R12, 0
star_loop:
    LOAD  R9,  R3, 0           ; x
    LOAD  R10, R3, 4           ; y
    LOAD  R11, R3, 8           ; z

    SUB   R11, R11, R21        ; acercarse un paso
    BGE   R11, R18, alive

    ; Se ha pasado de largo: nace otra al fondo. No se dibuja este frame --un
    ; frame de retraso en una estrella de las 256 no se ve, y ahorra repetir
    ; aqui la proyeccion.
    ADDI  R28, R19, 0          ; z = Z_MAX, nunca aleatoria (ver cabecera)
    JAL   R29, spawn
    BRA   next_star

alive:
    STORE R11, R3, 8

    ; ---- proyeccion en perspectiva ----
    DIV   R4, R9, R11
    ADDI  R4, R4, 160          ; centro de la pantalla
    DIV   R5, R10, R11
    ADDI  R5, R5, 120

    ; ---- recorte ----
    ; Imprescindible, y no como red de seguridad: una estrella cercana y de x
    ; grande se proyecta MUY fuera de la pantalla. Sin recortar, ese pixel
    ; caeria en otra fila del framebuffer, o fuera de el.
    BLT   R4, R0,  next_star
    BGE   R4, R22, next_star
    BLT   R5, R0,  next_star
    BGE   R5, R23, next_star

    ; ---- brillo segun la distancia ----
    MOVI  R28, 400
    BLT   R11, R28, near
    MOVI  R28, 800
    BLT   R11, R28, mid
    ORI   R6, R0, 0x4208       ; lejos: gris oscuro  (8, 16, 8)
    BRA   plot
mid:
    ORI   R6, R0, 0x9492       ; medio: gris         (18, 36, 18)
    BRA   plot
near:
    ORI   R6, R0, 0xFFFF       ; cerca: blanco
plot:
    JAL   R30, putpixel

next_star:
    ADDI  R3, R3, 12
    ADDI  R12, R12, 1
    BLT   R12, R20, star_loop

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R25, R2, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R28, R2, MMIO_VIDEO_SWAP_OFF
    BNE   R28, R0, wait_swap

    BRA   frame

; ------------------------------------------------------------
; rnd: siguiente valor del xorshift32.
;
; Avanza el estado R13 y lo deja tambien en R17. Vuelve por R31.
; ------------------------------------------------------------
rnd:
    SHL   R17, R13, R14        ; x ^= x << 13
    XOR   R13, R13, R17
    SHR   R17, R13, R15        ; x ^= x >> 17
    XOR   R13, R13, R17
    SHL   R17, R13, R16        ; x ^= x << 5
    XOR   R13, R13, R17
    ADDI  R17, R13, 0
    JR    R31

; ------------------------------------------------------------
; spawn: estrella nueva en [R3], con la z que traiga R28.
;
; La x y la y salen de los 16 bits altos de dos tiradas del xorshift. Un solo
; `SARI 16` hace dos cosas a la vez: se queda con la mitad alta y le extiende
; el signo, con lo que el rango es [-32768, 32767] centrado en cero sin restar
; nada. Ojo con la tentacion de escribir `SHLI 16` + `SARI 16`: eso es la mitad
; BAJA extendida en signo, que es justo la que no se quiere.
;
; Llama a `rnd`, que usa R31; por eso spawn enlaza por R29.
;
; Entrada: R3 (destino), R28 (z). Usa R17. Vuelve por R29.
; ------------------------------------------------------------
spawn:
    JAL   R31, rnd
    SARI  R17, R17, 16
    STORE R17, R3, 0           ; x
    JAL   R31, rnd
    SARI  R17, R17, 16
    STORE R17, R3, 4           ; y
    STORE R28, R3, 8           ; z
    JR    R29

; ------------------------------------------------------------
; putpixel: escribe el pixel (R4, R5) del color R6 en el buffer trasero.
;
; direccion = base + y*640 + x*2. No comprueba limites: el recorte ya esta
; hecho en el bucle, donde se sabe por que se descarta.
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
