; ============================================================
; swap_demo_fast.asm - la misma banda que swap_demo.asm, redibujando
; solo lo que cambia
;
; swap_demo.asm repinta las 240 lineas enteras cada frame: 38 400 escrituras
; mas cuatro instrucciones de bucle por cada una. Esta version pinta 32 lineas
; en lugar de 240 (borrar la banda vieja, dibujar la nueva), asi que hace
; 5 120 escrituras: 7,5 veces menos trabajo. Medido en la placa, el dibujo pasa
; de 96,6 ms a 13,2 ms por frame, una mejora de 7,3x que casa con el trabajo
; ahorrado.
;
; Lo que se ve en pantalla no es eso, sino el efecto de cruzar ese umbral:
; 13,2 ms caben en los 16,7 ms de un frame de video y 96,6 ms no. Con la espera
; al intercambio, un frame dibujado dura un numero entero de frames de video,
; asi que swap_demo.asm sale a 9,8 fps (uno de cada seis) y este se engancha a
; 59,3, o sea a los 60 del monitor. Sobran 3,5 ms por frame: a partir de aqui
; manda la pantalla, no la CPU.
;
; El detalle que lo hace interesante, y que no existe con un solo buffer:
; el buffer trasero NO contiene lo que se dibujo el frame pasado, sino lo del
; frame ANTERIOR a ese, porque los dos buffers se alternan. Asi que para
; borrar hay que recordar donde quedo la banda en CADA buffer por separado.
; Eso son R10 y R11, que rotan en cada intercambio. Equivocarse aqui deja un
; rastro de bandas verdes que no se borran nunca, y es el fallo clasico del
; doble buffer.
;
; Arranque: los dos buffers empiezan con basura, asi que los dos primeros
; frames borran 240 lineas en vez de 16. No hace falta codigo aparte para eso:
; basta con que el numero de lineas a borrar sea una variable (R28) que pasa
; de 240 a 16 cuando los dos buffers ya estan limpios.
;
; No se usa MUL: esta CPU declara el opcode pero no lo ejecuta. La direccion
; de una linea es base + y*640, y 640 = 512 + 128, o sea (y<<9) + (y<<7).
;
; Registros de video, en 0x80000000:
;   +0  FB_FRONT   +4  FB_BACK   +8  SWAP   +12  STATUS
;
; Convencion de registros:
;   R1  base del buffer trasero    R2  contador de lineas
;   R3  contador de palabras       R4  direccion de la linea
;   R5  temporal                   R6  puntero de escritura
;   R7  constante 1                R8  lectura de SWAP
;   R9  constante 0                R10 y de la banda en el buffer trasero
;   R11 y de la banda en el otro   R12 y del bloque que se pinta
;   R13 color del bloque           R14 constante 9   R15 constante 7
;   R26 lineas del bloque que se pinta
;   R20 base de los registros      R21 y de la banda, este frame
;   R22 y maximo                   R23 color de fondo
;   R24 color de la banda          R25 palabras por linea
;   R27 alto de la banda           R28 lineas a borrar (240 al principio)
;   R29 frames de arranque hechos  R30 constante 2
; ============================================================

start:
    MOVHI R20, 0x8000          ; registros de video en 0x80000000

    MOVHI R23, 0x001F
    ORI   R23, R23, 0x001F     ; fondo azul, en las dos mitades de la palabra
    MOVHI R24, 0x07E0
    ORI   R24, R24, 0x07E0     ; banda verde

    MOVI  R25, 160             ; palabras por linea (320 px de 16 bits)
    MOVI  R27, 16              ; alto de la banda
    MOVI  R28, 240             ; al principio hay que limpiar el buffer entero
    MOVI  R29, 0               ; frames de arranque completados
    MOVI  R30, 2               ; uno por buffer
    MOVI  R21, 0               ; y de la banda
    MOVI  R22, 224             ; 240 - alto de la banda
    MOVI  R10, 0               ; ninguno de los dos buffers tiene banda todavia
    MOVI  R11, 0
    MOVI  R14, 9               ; desplazamientos para *640
    MOVI  R15, 7
    MOVI  R7, 1
    MOVI  R9, 0

frame:
    LOAD  R1, R20, 4           ; R1 = FB_BACK; cambia en cada intercambio

    ; ---- borrar la banda que este buffer tenia ----
    ADDI  R12, R10, 0
    ADDI  R13, R23, 0          ; con el color de fondo
    ADDI  R26, R28, 0          ; 240 lineas al arrancar, 16 despues

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

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R7, R20, 8           ; SWAP = 1
wait_swap:
    LOAD  R8, R20, 8
    BNE   R8, R9, wait_swap

    ; Este buffer ya tiene la banda en R21; el que pasa a ser trasero es el
    ; otro, que la tiene donde diga R11. Por eso los dos valores rotan.
    ADDI  R5, R11, 0
    ADDI  R11, R21, 0
    ADDI  R10, R5, 0

    ; Cuando los dos buffers estan limpios, borrar 16 lineas basta.
    BGE   R29, R30, moved
    ADDI  R29, R29, 1
    BLT   R29, R30, moved
    ADDI  R28, R27, 0          ; borrar solo el alto de la banda

moved:
    ADDI  R21, R21, 2          ; mover la banda
    BLT   R21, R22, frame
    MOVI  R21, 0
    BRA   frame
