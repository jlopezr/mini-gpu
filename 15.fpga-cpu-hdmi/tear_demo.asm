; ============================================================
; tear_demo.asm - swap_demo.asm sin doble buffer, para ver las costuras
;
; Es el control negativo del hito D: la misma banda que baja, dibujada
; DIRECTAMENTE sobre el buffer que se esta mostrando. El hardware de video no
; espera a nadie, asi que lee las lineas de arriba mientras la CPU todavia
; esta escribiendo las de abajo, y en pantalla conviven dos frames a la vez.
;
; Solo hay dos diferencias con swap_demo.asm, y las dos van marcadas abajo:
;
;   1. LOAD R1, R20, 0   -> FB_FRONT, el buffer visible, en vez de FB_BACK.
;   2. No se pide SWAP ni se espera a que ocurra.
;
; Todo lo demas es identico, a proposito: si algo se ve distinto tiene que
; ser por el doble buffer y por nada mas.
;
; Que esperar. Medido en la placa, esta version tarda 96,6 ms en repintar las
; 240 lineas, o sea casi seis frames de video. El barrido da seis vueltas por
; cada pasada de la CPU, asi que no se ve una costura sino un frente de
; repintado bajando despacio por la pantalla: por encima la banda nueva, por
; debajo la vieja. Es tearing llevado al extremo, pero no se parece a lo que
; se ve en un juego; para eso esta tear_demo_fast.asm.
;
; Registros de video, en 0x80000000:
;   +0  FB_FRONT   +4  FB_BACK   +8  SWAP   +12  STATUS
;
; Convencion de registros: la misma que swap_demo.asm, menos R7 y R8, que
; aqui no hacen falta porque no hay intercambio que pedir ni que esperar.
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

frame:
    ; DIFERENCIA 1: el buffer visible, no el trasero. Aqui es donde se rompe
    ; la imagen: se escribe justo lo que el barrido esta leyendo.
    LOAD  R1, R20, 0           ; R1 = FB_FRONT
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

    ; DIFERENCIA 2: swap_demo.asm pide aqui el intercambio y espera a que el
    ; hardware lo aplique al empezar un frame nuevo. Al quitarlo, nada
    ; sincroniza el dibujo con el barrido.

    ADDI  R21, R21, 2          ; mover la banda
    BLT   R21, R22, frame
    MOVI  R21, 0
    BRA   frame
