; ============================================================
; input_paint.asm - pintar con el raton y cambiar de color con el teclado
;
; Demo de INPUT (mmio.md §25) sobre el framebuffer de VIDEO. Sin consola, sin
; doble buffer: dibuja directamente en el buffer frontal.
;
;   mover el raton            mueve el pincel
;   mantener el boton izq.    pinta (un cuadrado de 2x2 por cada movimiento)
;   R G B Y C M W             rojo, verde, azul, amarillo, cian, magenta, blanco
;   cualquier otra tecla      un color que sale de su Usage ID
;   barra espaciadora         borra la pantalla
;
; El raton de INPUT es RELATIVO: el programa no sabe donde esta el puntero, solo
; cuanto se ha movido, asi que el pincel arranca en el centro y se mueve desde
; ahi. La posicion se lleva en medios pixeles de framebuffer: la ventana enseña
; el framebuffer a doble tamano, y asi el pincel sigue al puntero a su velocidad.
;
; Se ejecuta con ventana, y como no acaba solo, con un limite generoso:
;
;   sim-cpu 2.cpu-sim-func\examples\input_paint.asm --window --run-limit 2000000000
;
; Registros:
;   R20 base de VIDEO     R21 base de INPUT     R22 framebuffer (0x00100000)
;   R10 x, R11 y          en medios pixeles (0..639, 0..479)
;   R12 color RGB565      R13 boton izquierdo pulsado
; ============================================================

.include "mmio.inc"

start:
    LI    R20, MMIO_VIDEO_BASE
    LI    R21, MMIO_INPUT_BASE
    MOVHI R22, 0x0010                       ; framebuffer en 0x00100000
    STORE R22, R20, MMIO_VIDEO_FB_FRONT_OFF
    STORE R22, R20, MMIO_VIDEO_FB_BACK_OFF
    MOVI  R3, MMIO_VIDEO_MODE_SCANOUT
    STORE R3, R20, MMIO_VIDEO_CTRL_OFF

    MOVI  R10, 320                          ; pincel en el centro (160, 120)
    MOVI  R11, 240
    MOVI  R12, -1                           ; blanco (STOREH guarda los 16 bits bajos)
    MOVI  R13, 0
    BRA   do_clear

loop:
    ; Un evento por vuelta. COUNT (STATUS 15:0) dice si hay uno: el valor de
    ; EVENT_DATA por si solo no lo dice.
    LOAD  R6, R21, MMIO_INPUT_STATUS_OFF
    ANDI  R6, R6, 0xFF
    BEQ   R6, R0, loop
    LOAD  R7, R21, MMIO_INPUT_EVENT_DATA_OFF

    SHRI  R8, R7, 24                        ; tipo de evento
    MOVI  R9, MMIO_INPUT_TYPE_MOUSE_MOVE
    BEQ   R8, R9, on_move
    MOVI  R9, MMIO_INPUT_TYPE_MOUSE_BUTTON
    BEQ   R8, R9, on_button

    ; ---- tecla (TYPE_KEY) ----
    ANDI  R9, R7, 0xFF                      ; Usage ID; 0 = cambio de modificadores
    BEQ   R9, R0, loop
    SHRI  R4, R7, 8
    ANDI  R4, R4, 1                         ; solo las pulsaciones, no las liberaciones
    BEQ   R4, R0, loop
    MOVI  R4, 0x2C                          ; barra espaciadora
    BEQ   R9, R4, do_clear

    ; Colores con nombre (Usage IDs de las letras: R=0x15 G=0x0A B=0x05 Y=0x1C
    ; C=0x06 M=0x10 W=0x1A).
    MOVI  R4, 0x15
    BNE   R9, R4, not_red
    MOVI  R12, -2048                        ; 0xF800
    BRA   loop
not_red:
    MOVI  R4, 0x0A
    BNE   R9, R4, not_green
    MOVI  R12, 2016                         ; 0x07E0
    BRA   loop
not_green:
    MOVI  R4, 0x05
    BNE   R9, R4, not_blue
    MOVI  R12, 31                           ; 0x001F
    BRA   loop
not_blue:
    MOVI  R4, 0x1C
    BNE   R9, R4, not_yellow
    MOVI  R12, -32                          ; 0xFFE0
    BRA   loop
not_yellow:
    MOVI  R4, 0x06
    BNE   R9, R4, not_cyan
    MOVI  R12, 2047                         ; 0x07FF
    BRA   loop
not_cyan:
    MOVI  R4, 0x10
    BNE   R9, R4, not_magenta
    MOVI  R12, -2017                        ; 0xF81F
    BRA   loop
not_magenta:
    MOVI  R4, 0x1A
    BNE   R9, R4, other_key
    MOVI  R12, -1                           ; 0xFFFF
    BRA   loop
other_key:
    SHLI  R12, R9, 11                       ; el resto: color a partir del Usage ID
    SHLI  R5, R9, 5
    OR    R12, R12, R5
    OR    R12, R12, R9
    BRA   loop

on_button:
    ANDI  R9, R7, 0xFF
    BNE   R9, R0, loop                      ; solo el boton izquierdo (0)
    SHRI  R13, R7, 8
    ANDI  R13, R13, 1                       ; DOWN
    BEQ   R13, R0, loop
    BRA   plot

on_move:
    SHLI  R4, R7, 20                        ; DX, signed12 en 11:0
    SARI  R4, R4, 20
    SHRI  R5, R7, 12                        ; DY, signed12 en 23:12
    SHLI  R5, R5, 20
    SARI  R5, R5, 20
    ADD   R10, R10, R4
    ADD   R11, R11, R5

    BGE   R10, R0, x_not_negative           ; mantener el pincel dentro de 320x240
    MOVI  R10, 0
x_not_negative:
    MOVI  R9, 639
    BLT   R10, R9, x_inside
    MOVI  R10, 639
x_inside:
    BGE   R11, R0, y_not_negative
    MOVI  R11, 0
y_not_negative:
    MOVI  R9, 479
    BLT   R11, R9, y_inside
    MOVI  R11, 479
y_inside:
    BEQ   R13, R0, loop                     ; sin boton, solo se mueve

plot:
    SHRI  R14, R11, 1                       ; y en pixeles
    SHLI  R4, R14, 8                        ; y * 320 = (y << 8) + (y << 6)
    SHLI  R5, R14, 6
    ADD   R4, R4, R5
    SHRI  R14, R10, 1                       ; x en pixeles
    ADD   R4, R4, R14
    SHLI  R4, R4, 1                         ; * 2 bytes por pixel
    ADD   R4, R4, R22
    STOREH R12, R4, 0
    STOREH R12, R4, 2
    STOREH R12, R4, 640
    STOREH R12, R4, 642
    BRA   loop

do_clear:
    ADDI  R3, R22, 0
    MOVHI R5, 0x0002
    ORI   R5, R5, 0x5800                    ; 320 * 240 * 2 = 153600 bytes
    ADD   R4, R22, R5
clear_word:
    STORE R0, R3, 0
    ADDI  R3, R3, 4
    BLT   R3, R4, clear_word
    BRA   loop
