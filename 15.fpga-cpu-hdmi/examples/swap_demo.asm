; ============================================================
; swap_demo.asm - banda horizontal que baja, con doble buffer
;
; Demostracion del hito D. La prueba util no es que se vea la banda, sino
; comparar dos comportamientos:
;
;   - Con el swap sincronizado (este programa tal cual) la banda debe bajar
;     limpia, sin que la imagen se parta nunca.
;   - Si se quita la espera de `wait_swap`, o se dibuja directamente sobre
;     FB_FRONT en lugar de FB_BACK, debe aparecer tearing: una costura
;     horizontal donde conviven dos frames.
;
; Registros de video, en 0x80000000:
;   +0  FB_FRONT   +4  FB_BACK   +8  SWAP   +12  STATUS
;
; El framebuffer es RGB565 de 320x240. Cada palabra de 32 bits son DOS
; pixeles, asi que los colores se repiten en las dos mitades y una linea son
; 160 palabras.
;
; Convencion de registros:
;   R1  puntero de escritura        R2  linea actual
;   R3  palabra dentro de la linea  R4  direccion de la palabra
;   R5  color de esta linea         R6  ultima linea de la banda
;   R7  constante 1                 R8  lectura de SWAP
;   R9  constante 0                 R20 base de los registros de video
;   R21 y de la banda               R22 y maximo
;   R23 color de fondo              R24 color de la banda
;   R25 palabras por linea          R26 lineas
; ============================================================

start:
    MOVHI R20, 0x8000          ; registros de video en 0x80000000

    MOVHI R23, 0x001F
    ORI   R23, R23, 0x001F     ; fondo azul, en las dos mitades de la palabra
    MOVHI R24, 0x07E0
    ORI   R24, R24, 0x07E0     ; banda verde

    MOVI  R25, 160             ; palabras por linea (320 px de 16 bits)
    MOVI  R26, 240             ; lineas
    MOVI  R21, 0               ; y de la banda
    MOVI  R22, 224             ; 240 - alto de la banda
    MOVI  R7, 1
    MOVI  R9, 0

frame:
    LOAD  R1, R20, 4           ; R1 = FB_BACK; cambia en cada swap
    MOVI  R2, 0

line_loop:
    ADDI  R5, R23, 0           ; por defecto, fondo
    BLT   R2, R21, line_draw   ; por encima de la banda
    ADDI  R6, R21, 16          ; alto de la banda
    BGE   R2, R6, line_draw    ; por debajo de la banda
    ADDI  R5, R24, 0           ; dentro: color de banda

line_draw:
    MOVI  R3, 0
    ADDI  R4, R1, 0

word_loop:
    STORE R5, R4, 0
    ADDI  R4, R4, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, word_loop

    ADDI  R1, R1, 640          ; siguiente linea: 320 px * 2 bytes
    ADDI  R2, R2, 1
    BLT   R2, R26, line_loop

    ; El buffer esta dibujado: pedir el intercambio y esperar a que el
    ; hardware lo aplique, que solo ocurre al empezar un frame nuevo. Sin esta
    ; espera se dibujaria sobre el buffer que se esta mostrando.
    STORE R7, R20, 8           ; SWAP = 1
wait_swap:
    LOAD  R8, R20, 8
    BNE   R8, R9, wait_swap

    ADDI  R21, R21, 2          ; mover la banda
    BLT   R21, R22, frame
    MOVI  R21, 0
    BRA   frame
