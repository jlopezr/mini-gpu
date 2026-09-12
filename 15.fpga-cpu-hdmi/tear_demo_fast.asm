; ============================================================
; tear_demo_fast.asm - la costura limpia, en un solo buffer
;
; tear_demo.asm tarda 109 ms en repintar las 240 lineas, seis frames y medio
; de video, asi que lo que se ve es un frente de repintado bajando despacio,
; no una costura. Esta version pinta solo las 32 lineas que cambian, como
; swap_demo_fast.asm, y tarda 19,4 ms medidos en la placa.
;
; Y ahi esta la gracia: 19,4 ms contra los 16,7 ms que dura un frame de video.
; La CPU y el barrido van casi a la misma velocidad, pero no exactamente, asi
; que el punto donde se cruzan se desplaza poco a poco. En pantalla eso es una
; costura horizontal que recorre la imagen cada 120 ms mas o menos: por encima
; del corte la banda ya se ha movido, por debajo todavia no. Esa es la costura
; que se reconoce de un juego sin vsync.
;
; El ritmo NO esta ajustado a mano para que salga asi; sale de lo que tarda
; esta CPU en escribir 5 120 palabras compitiendo con el video por la SDRAM.
;
; Diferencias con swap_demo_fast.asm:
;
;   1. LOAD R1, R20, 0   -> FB_FRONT, el buffer visible.
;   2. No se pide SWAP ni se espera.
;   3. Un solo registro de posicion anterior en vez de dos. Con doble buffer
;      hacen falta R10 y R11 porque el buffer trasero lleva lo del frame
;      ANTERIOR al pasado; con un solo buffer lo que hay en pantalla es
;      exactamente lo que se dibujo la ultima vez, asi que basta con R10.
;   4. Un solo borrado completo al arrancar, no dos, por lo mismo.
;
; Registros de video, en 0x80000000:
;   +0  FB_FRONT   +4  FB_BACK   +8  SWAP   +12  STATUS
;
; Convencion de registros:
;   R1  base del buffer visible    R2  contador de lineas
;   R3  contador de palabras       R4  direccion de la linea
;   R5  temporal                   R6  puntero de escritura
;   R10 y de la banda ahora mismo en pantalla
;   R12 y del bloque que se pinta  R13 color del bloque
;   R14 constante 9   R15 constante 7
;   R20 base de los registros      R21 y de la banda, este frame
;   R22 y maximo                   R23 color de fondo
;   R24 color de la banda          R25 palabras por linea
;   R26 lineas del bloque que se pinta
;   R27 alto de la banda           R28 lineas a borrar (240 la primera vez)
; ============================================================

start:
    MOVHI R20, 0x8000          ; registros de video en 0x80000000

    MOVHI R23, 0x001F
    ORI   R23, R23, 0x001F     ; fondo azul, en las dos mitades de la palabra
    MOVHI R24, 0x07E0
    ORI   R24, R24, 0x07E0     ; banda verde

    MOVI  R25, 160             ; palabras por linea (320 px de 16 bits)
    MOVI  R27, 16              ; alto de la banda
    MOVI  R28, 240             ; la primera pasada limpia el buffer entero
    MOVI  R21, 0               ; y de la banda
    MOVI  R22, 224             ; 240 - alto de la banda
    MOVI  R10, 0               ; todavia no hay banda en pantalla
    MOVI  R14, 9               ; desplazamientos para *640
    MOVI  R15, 7

frame:
    ; DIFERENCIA 1: el buffer visible, no el trasero.
    LOAD  R1, R20, 0           ; R1 = FB_FRONT

    ; ---- borrar la banda que hay en pantalla ----
    ADDI  R12, R10, 0
    ADDI  R13, R23, 0          ; con el color de fondo
    ADDI  R26, R28, 0          ; 240 lineas la primera vez, 16 despues

    SHL   R4, R12, R14         ; y*512
    SHL   R5, R12, R15         ; y*128
    ADD   R4, R4, R5           ; y*640
    ADD   R4, R4, R1           ; + base del buffer
    MOVI  R2, 0

erase_line:
    MOVI  R3, 0
    ADDI  R6, R4, 0
erase_word:
    STORE R13, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, erase_word
    ADDI  R4, R4, 640
    ADDI  R2, R2, 1
    BLT   R2, R26, erase_line

    ADDI  R28, R27, 0          ; a partir de aqui, solo el alto de la banda

    ; ---- dibujar la banda en su sitio nuevo ----
    ADDI  R12, R21, 0
    ADDI  R13, R24, 0          ; con el color de la banda
    ADDI  R26, R27, 0          ; siempre 16 lineas

    SHL   R4, R12, R14
    SHL   R5, R12, R15
    ADD   R4, R4, R5
    ADD   R4, R4, R1
    MOVI  R2, 0

draw_line:
    MOVI  R3, 0
    ADDI  R6, R4, 0
draw_word:
    STORE R13, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, draw_word
    ADDI  R4, R4, 640
    ADDI  R2, R2, 1
    BLT   R2, R26, draw_line

    ; DIFERENCIA 2: swap_demo_fast.asm pide aqui el intercambio y espera.
    ; Sin esa espera, nada sincroniza el dibujo con el barrido.

    ; DIFERENCIA 3: lo que hay en pantalla es lo ultimo que se dibujo.
    ADDI  R10, R21, 0

    ADDI  R21, R21, 2          ; mover la banda
    BLT   R21, R22, frame
    MOVI  R21, 0
    BRA   frame
