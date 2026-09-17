; ============================================================
; fullframe.asm - dibujo minimo para el banco de RTL a resolucion completa
;
; Pinta una «L» azul --la linea de arriba y la columna de la izquierda-- y un
; cuadrado blanco fijo, y pide el intercambio. En bucle.
;
; Esta escrito para que la SIMULACION termine. Repintar el fondo entero son
; 38 400 palabras por frame, unos 1,35 M de ciclos, y en `iverilog` eso son
; decenas de segundos por frame. Esto son 912 palabras: el fondo se queda como
; lo dejo el modelo de SDRAM, que es todo ceros, o sea negro, y por tanto
; igual de determinista.
;
; La «L» no es simetrica a proposito. Un marco completo se ve igual si alguien
; intercambia los ejes; una linea arriba y una columna a la izquierda, no.
;
; El cuadrado no se mueve: cada buffer se dibuja una vez de cada dos
; intercambios, asi que un cuadrado movil dejaria rastro en el buffer que no
; toca y el frame esperado dependeria de la historia.
;
; Registros:
;   R1  base del buffer trasero   R2  contador de lineas
;   R3  contador de palabras      R4  direccion de la linea
;   R5  temporal                  R6  puntero de escritura
;   R7  constante 1               R8  lectura de SWAP
;   R9  constante 0               R14 constante 9   R15 constante 7
;   R16 x del cuadrado            R17 y del cuadrado
;   R20 base de los registros     R22 lineas (240)
;   R23 color de la L             R24 color del cuadrado
;   R25 palabras por linea (160)  R26 ancho del cuadrado en palabras (16)
;   R27 alto del cuadrado (32)
; ============================================================

start:
    MOVHI R20, 0x8000

    ; Elegir donde vive el framebuffer. Tras el reset las dos bases valen
    ; cero --el framebuffer es una decision del programa, no una reserva
    ; que el hardware impone-- asi que heredarlas seria dibujar sobre el
    ; propio programa. La direccion es la de siempre; lo que cambia es que
    ; ahora hay que escribirla.
    MOVHI R30, 0x0100
    STORE R30, R20, 0          ; FB_FRONT
    MOVHI R30, 0x0102
    ORI   R30, R30, 0x5800
    STORE R30, R20, 4          ; FB_BACK, un frame mas arriba

    ; Encender el scanout. Tras el reset el modo es PATTERN --la memoria
    ; recien encendida contiene basura, asi que arrancar leyendola daria
    ; una salida indefinida-- y un programa que dibuja tiene que pedir
    ; que se vea lo que dibuja. Ver video_registers.v, VIDEO_CTRL.
    MOVI  R30, 2               ; SCANOUT
    STORE R30, R20, 24         ; VIDEO_CTRL

    MOVHI R23, 0x001F
    ORI   R23, R23, 0x001F     ; azul
    MOVHI R24, 0xFFFF
    ORI   R24, R24, 0xFFFF     ; blanco

    MOVI  R7, 1
    MOVI  R9, 0
    MOVI  R14, 9
    MOVI  R15, 7
    MOVI  R22, 240
    MOVI  R25, 160
    MOVI  R26, 16              ; 32 px
    MOVI  R27, 32
    MOVI  R16, 64              ; x del cuadrado, en pixeles
    MOVI  R17, 48              ; y

frame:
    LOAD  R1, R20, 4           ; FB_BACK

    ; ---- linea de arriba, y = 0 ----
    ADDI  R6, R1, 0
    MOVI  R3, 0
top_line:
    STORE R23, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, top_line

    ; ---- columna de la izquierda, x = 0 y 1 ----
    ADDI  R6, R1, 0
    MOVI  R2, 0
left_col:
    STORE R23, R6, 0
    ADDI  R6, R6, 640          ; una linea son 320 px de 2 bytes
    ADDI  R2, R2, 1
    BLT   R2, R22, left_col

    ; ---- el cuadrado ----
    ; direccion = base + y*640 + x*2
    SHL   R4, R17, R14         ; y*512
    SHL   R5, R17, R15         ; y*128
    ADD   R4, R4, R5
    ADD   R4, R4, R1
    SHL   R5, R16, R7          ; x*2
    ADD   R4, R4, R5

    MOVI  R2, 0
sq_line:
    MOVI  R3, 0
    ADDI  R6, R4, 0
sq_word:
    STORE R24, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R26, sq_word
    ADDI  R4, R4, 640
    ADDI  R2, R2, 1
    BLT   R2, R27, sq_line

    ; ---- pedir el intercambio y esperar ----
    STORE R7, R20, 8
wait_swap:
    LOAD  R8, R20, 8
    BNE   R8, R9, wait_swap

    BRA   frame
