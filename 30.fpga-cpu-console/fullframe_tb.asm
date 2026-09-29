; ============================================================
; fullframe_tb.asm - fullframe.asm con las bases bajas, para el banco de RTL
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

.include "mmio.inc"

; Las dos bases, y la unica diferencia con `examples/fullframe.asm`, que es
; este mismo programa para la placa. Alli las bases son 0x01000000 y
; 0x01025800; aqui no caben, porque el modelo de SDRAM guarda 4 bancos x 128
; filas, la fila sale de los bits [23:11] de la direccion de palabra, y
; 0x01000000 pide la fila 4096 --que el modelo denuncia como violacion, una
; por acceso, asi que el sintoma es «60000 violaciones JEDEC» y no «direccion
; mala»--. `x.tests/test_fullframe_fixture.py` obliga a que el cuerpo de los
; dos ficheros sea identico y a que `fullframe.hex` salga de ESTE.
.equ FB_FRONT_ADDR, 0x00010000
.equ FB_BACK_ADDR, 0x00035800      ; FB_FRONT + 320*240*2

start:
    LI    R20, MMIO_VIDEO_BASE
    ; Las bases arrancan a cero --el framebuffer es una decision del programa,
    ; no una reserva que el hardware impone-- asi que heredarlas seria dibujar
    ; sobre el propio programa.
    LI    R30, FB_FRONT_ADDR
    STORE R30, R20, MMIO_VIDEO_FB_FRONT_OFF          ; FB_FRONT
    LI    R30, FB_BACK_ADDR
    STORE R30, R20, MMIO_VIDEO_FB_BACK_OFF          ; FB_BACK, un frame mas arriba

    ; Encender el scanout. Tras el reset el modo es PATTERN --la memoria
    ; recien encendida contiene basura, asi que arrancar leyendola daria
    ; una salida indefinida-- y un programa que dibuja tiene que pedir
    ; que se vea lo que dibuja. Ver video_registers.v, VIDEO_CTRL.
    MOVI  R30, 2               ; SCANOUT
    STORE R30, R20, MMIO_VIDEO_CTRL_OFF         ; VIDEO_CTRL

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
    LOAD  R1, R20, MMIO_VIDEO_FB_BACK_OFF           ; FB_BACK

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
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF
    BNE   R8, R9, wait_swap

    BRA   frame
