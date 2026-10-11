; ============================================================
; bounce.asm - el cuadrado que rebota en los bordes
;
; Un cuadrado blanco de 32x32 sobre fondo azul, moviendose en diagonal y
; rebotando en los cuatro bordes. Como caso de prueba cubre cosas que una banda
; horizontal no puede:
;
;   - **Errores de pitch.** En una banda, todos los pixeles de una linea son
;     iguales, asi que una zancada de linea equivocada casi no se nota. Un
;     cuadrado se deforma o se parte inmediatamente.
;   - **Los bordes.** El rebote ocurre exactamente en 0 y en el maximo, asi que
;     un error de uno en el recorte se ve como un cuadrado que se sale o que
;     rebota una fila antes.
;   - **Escrituras parciales de linea.** El cuadrado se pinta ENCIMA del fondo
;     ya escrito, y ocupa 16 palabras de las 160 de la linea. Eso obliga al
;     bufer de combinacion de escrituras a volcar y empezar linea en cada
;     pasada, que es justo su camino menos transitado.
;
; Determinismo
; ------------
;
; La posicion es una funcion pura del numero de intercambio, asi que el frame
; que se captura al parar en el intercambio N esta definido sin ambiguedad.
; `reference.py` hace exactamente esta misma cuenta.
;
; El fondo se repinta ENTERO en cada frame, y eso es una decision, no un
; descuido. La alternativa --borrar solo donde estaba el cuadrado-- es lo que
; hace un programa de verdad y lo que hacen las demos de la 16, pero obliga a
; recordar la posicion anterior EN CADA BUFFER POR SEPARADO, porque con doble
; buffer el trasero no contiene lo del frame pasado sino lo del anterior a ese.
; Eso es interesante y merece su propio caso; aqui estorba, porque un fallo en
; esa contabilidad se confundiria con un fallo del hardware. Repintar entero
; hace que CUALQUIER frame sea correcto por si mismo, sin historia.
;
; Cuesta 38 400 palabras por frame en vez de 512, o sea unos 33 ms: dos frames
; de video. Para un caso de prueba da igual.
;
; Convencion de registros:
;   R1  base del buffer trasero    R2  contador de lineas
;   R3  contador de palabras       R4  direccion de escritura
;   R5  temporal                   R6  puntero de escritura
;   R7  constante 1                R8  lectura de SWAP
;   R0  cero, cableado por la ISA
;   R14 constante 9   R15 constante 7      (para *640)
;   R16 x del cuadrado, en pixeles         R17 y del cuadrado
;   R18 dx                                 R19 dy
;   R20 base de los registros de video
;   R22 lineas de pantalla (240)           R23 color de fondo
;   R24 color del cuadrado                 R25 palabras por linea (160)
;   R26 palabras de ancho del cuadrado (16, o sea 32 px)
;   R27 lineas de alto del cuadrado (32)
;   R28 x maxima (320-32 = 288)            R29 y maxima (240-32 = 208)
; ============================================================

.include "mmio.inc"

start:
    LI    R20, MMIO_VIDEO_BASE          ; registros de video

    ; Las dos bases se las pone el programa, como el resto de los ejemplos de
    ; video. Arrancan a cero desde la fase 3.5 --cero no pretende ser una
    ; direccion util-- asi que heredarlas era dibujar sobre el propio programa
    ; en la direccion cero. Separadas por 0x25800, justo un frame de 320x240
    ; en RGB565, y las dos alineadas a 16 como pide MMIO_VIDEO_FB_ALIGN.
    ; R5 es el temporal del programa y aqui no hay nada vivo todavia.
    MOVHI R5, 0x0100
    STORE R5, R20, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT = 0x01000000
    MOVHI R5, 0x0102
    ORI   R5, R5, 0x5800
    STORE R5, R20, MMIO_VIDEO_FB_BACK_OFF            ; FB_BACK  = 0x01025800

    MOVHI R23, 0x001F
    ORI   R23, R23, 0x001F     ; azul, en las dos mitades de la palabra
    MOVHI R24, 0xFFFF
    ORI   R24, R24, 0xFFFF     ; blanco

    MOVI  R7, 1
    MOVI  R14, 9               ; desplazamientos para *640
    MOVI  R15, 7
    MOVI  R22, 240
    MOVI  R25, 160
    MOVI  R26, 16              ; 32 px = 16 palabras
    MOVI  R27, 32
    MOVI  R28, 288             ; 320 - 32
    MOVI  R29, 208             ; 240 - 32

    ; Posicion y velocidad iniciales. Con paso 4 y los maximos multiplos de 4,
    ; el rebote cae EXACTAMENTE en el borde y no hay que recortar nada: la
    ; posicion nunca se pasa. Eso mantiene la cuenta de reference.py trivial.
    MOVI  R16, 0
    MOVI  R17, 0
    MOVI  R18, 4
    MOVI  R19, 4

frame:
    LOAD  R1, R20, MMIO_VIDEO_FB_BACK_OFF           ; R1 = FB_BACK, cambia en cada intercambio

    ; ---- fondo completo ----
    ADDI  R4, R1, 0
    MOVI  R2, 0
bg_line:
    MOVI  R3, 0
    ADDI  R6, R4, 0
bg_word:
    STORE R23, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, bg_word
    ADDI  R4, R4, 640
    ADDI  R2, R2, 1
    BLT   R2, R22, bg_line

    ; ---- el cuadrado ----
    ; direccion = base + y*640 + x*2
    ;   una linea son 320 px de 2 bytes = 640 bytes
    ;   un pixel son 2 bytes, asi que x pixeles son x*2 bytes
    SHL   R4, R17, R14         ; y*512
    SHL   R5, R17, R15         ; y*128
    ADD   R4, R4, R5           ; y*640
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

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF
    BNE   R8, R0, wait_swap

    ; ---- mover, y rebotar en los bordes ----
    ; El movimiento va DESPUES del intercambio, asi que lo que se ve tras el
    ; intercambio N es la posicion del paso N-1. reference.py cuenta igual.
    ADD   R16, R16, R18
    BLT   R16, R0, x_low       ; x < 0, con signo
    BLT   R28, R16, x_high     ; x > maximo
    BRA   x_done
x_low:
    MOVI  R16, 0
    SUB   R18, R0, R18         ; dx = -dx
    BRA   x_done
x_high:
    ADDI  R16, R28, 0
    SUB   R18, R0, R18
x_done:

    ADD   R17, R17, R19
    BLT   R17, R0, y_low
    BLT   R29, R17, y_high
    BRA   y_done
y_low:
    MOVI  R17, 0
    SUB   R19, R0, R19         ; dy = -dy
    BRA   y_done
y_high:
    ADDI  R17, R29, 0
    SUB   R19, R0, R19
y_done:

    BRA   frame
