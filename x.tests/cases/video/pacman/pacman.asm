; ============================================================
; pacman.asm - demo de Pac-Man que se juega sola
;
; Una pantalla de carga con el logo, y despues un laberinto de 40x30 tiles de
; 8x8 donde Pac-Man busca pastillas y cuatro fantasmas le persiguen. Nadie
; toca un teclado: Pac-Man decide en cada cruce y los fantasmas tiran un dado.
;
; El mapa de tiles
; ----------------
;
; `tiles` es un byte por tile, 40x30 = 1200 bytes, y es la UNICA fuente de
; verdad: de ahi sale lo que se pinta, ahi se detectan los muros al mover, y
; ahi se borran las pastillas al comerlas. No hay una lista de pastillas
; aparte que pudiera desincronizarse del dibujo.
;
; Se decodifica al arrancar desde `maze_ascii`, que esta escrito en el fuente
; como 30 filas de texto para que el laberinto se pueda editar mirandolo. El
; decodificador **salta cualquier byte menor que 32**, y eso no es una
; tolerancia gratuita: `.string` mete un NUL y rellena hasta multiplo de 4, asi
; que entre fila y fila hay de 1 a 4 bytes de relleno. Saltarlos por valor en
; vez de suponer una zancada de 44 hace que el decodificador siga siendo
; correcto si alguien cambia el ancho de una fila.
;
; Movimiento
; ----------
;
; Las entidades se mueven 2 px por frame, o sea 4 frames por tile, y **solo
; deciden cuando estan alineadas** con la rejilla (x e y multiplos de 8). Eso
; da movimiento suave sin que la logica tenga que razonar en medios tiles:
; entre decision y decision una entidad no puede atravesar nada, porque el
; tile de destino ya se comprobo al entrar.
;
; Doble buffer: por que cada entidad guarda DOS posiciones anteriores
; ------------------------------------------------------------------
;
; El laberinto se pinta entero una vez en cada buffer al empezar, y a partir de
; ahi cada frame solo borra y redibuja los 2x2 tiles bajo cada entidad. Son 20
; tiles por frame en vez de 1200.
;
; Lo que cuesta ese ahorro es contabilidad, y es el error clasico del doble
; buffer: el buffer trasero no contiene el frame anterior sino el de **hace
; dos**, asi que borrar usando la posicion del frame pasado deja un rastro de
; Pac-Men amarillos que no se limpia nunca. Por eso `E_PX0/E_PY0` y
; `E_PX1/E_PY1`: cada entidad recuerda donde se dibujo en CADA buffer por
; separado, y `parity` dice cual toca. Es la misma contabilidad que hace
; `starfield-fast`, y el mismo motivo.
;
; El borrado repinta desde `tiles`, no con negro, asi que las paredes y las
; pastillas por las que pasa una entidad reaparecen solas. Y una pastilla
; comida desaparece de los dos buffers sin trabajo extra: los dos frames
; siguientes borran ese tile en uno y en otro, ya con el mapa actualizado.
;
; Convencion de registros
; -----------------------
;   R0   cero, cableado por la ISA
;   R25  base de `ent` (las cinco entidades)
;   R26  base de `tiles`
;   R27  base del buffer donde se esta pintando AHORA
;   R28  base de los registros de video
;   R29  puntero de pila (arranca en `stack_top` y crece hacia abajo)
;   R31  enlace de retorno, lo escribe JAL
;   R1-R9  temporales libres: una rutina los usa sin avisar
;   R10-R12 los salva la rutina que los use, no quien llama
; ============================================================

.include "mmio.inc"

; ---- geometria ----
.equ COLS,        40
.equ ROWS,        30
.equ TILE,        8
.equ SCR_W,       320
.equ PITCH,       640           ; 320 px * 2 bytes
.equ NENT,        5             ; Pac-Man + 4 fantasmas

; ---- los dos framebuffers ----
; Separados por 0x40000 (256 KiB), muy por encima de los 153 600 bytes que
; ocupa un frame, y los dos alineados a 16 como pide MMIO_VIDEO_FB_ALIGN.
.equ FB0,         0x01000000
.equ FB1,         0x01040000

; ---- codigos de tile ----
.equ T_EMPTY,     0
.equ T_WALL,      1
.equ T_PILL,      2
.equ T_POWER,     3

; ---- campos de una entidad (40 bytes) ----
.equ E_SIZE,      40
.equ E_X,         0
.equ E_Y,         4
.equ E_DX,        8
.equ E_DY,        12
.equ E_PX0,       16            ; donde se dibujo en el buffer de paridad 0
.equ E_PY0,       20
.equ E_PX1,       24            ; ... y en el de paridad 1
.equ E_PY1,       28
.equ E_COL,       32
.equ E_BM,        36            ; direccion de su bitmap 8x8

; ---- colores RGB565 ----
.equ C_BLACK,     0x0000
.equ C_WALL,      0x0014        ; azul oscuro
.equ C_PILL,      0xFFDA        ; blanco calido
.equ C_PAC,       0xFFE0        ; amarillo
.equ C_G0,        0xF800        ; rojo
.equ C_G1,        0x07FF        ; cian
.equ C_G2,        0xFD9F        ; rosa
.equ C_G3,        0xFD20        ; naranja

; Los mismos colores duplicados en las dos mitades de una palabra, para poder
; rellenar un tile de dos pixeles por STORE en vez de uno por STOREH.
.equ C_BLACK_W,   0x00000000
.equ C_WALL_W,    0x00140014

; Cuantos intercambios dura el logo antes de empezar la partida. Se cuenta en
; SWAPS y no en tiempo real a proposito: el simulador no modela el tiempo, asi
; que una espera por ciclos duraria lo que le diese la gana alli. A 60 Hz son
; unos dos segundos.
.equ LOGO_SWAPS,  120

; =========================================================================
; Arranque
; =========================================================================
.text

start:
    LI    R28, MMIO_VIDEO_BASE
    LI    R29, stack_top
    LI    R26, tiles
    LI    R25, ent

    ; Las bases de los dos buffers las fijamos nosotros. En placa estos
    ; registros solo los reinicia el reset del bitstream, asi que lo que
    ; dejase el programa anterior sigue ahi: no se puede suponer nada.
    LI    R1, FB0
    STORE R1, R28, MMIO_VIDEO_FB_FRONT_OFF
    LI    R1, FB1
    STORE R1, R28, MMIO_VIDEO_FB_BACK_OFF

    ; Semilla del xorshift. Cualquier valor menos cero, que es el punto fijo.
    LI    R1, seed_rng
    LI    R2, 0x2545F491
    STORE R2, R1, 0

    JAL   R31, decode_maze

    ; ---- pantalla de carga ----
    ; El logo va a los DOS buffers antes de encender el scanout, para que el
    ; primer intercambio no muestre un buffer sin escribir.
    LI    R27, FB0
    JAL   R31, draw_logo
    LI    R27, FB1
    JAL   R31, draw_logo

    MOVI  R1, MMIO_VIDEO_MODE_SCANOUT
    STORE R1, R28, MMIO_VIDEO_CTRL_OFF

    MOVI  R12, LOGO_SWAPS
logo_hold:
    JAL   R31, swap_and_wait
    ADDI  R12, R12, -1
    BNE   R12, R0, logo_hold

    ; ---- el laberinto, tambien en los dos buffers ----
    JAL   R31, reset_entities
    LI    R27, FB0
    JAL   R31, draw_maze
    LI    R27, FB1
    JAL   R31, draw_maze

    ; `parity` dice en que mitad del par E_PX0/E_PX1 se anota lo que se dibuja
    ; este frame. Arranca en 0 y alterna con cada intercambio.
    LI    R1, parity
    STORE R0, R1, 0

; =========================================================================
; Bucle de juego
; =========================================================================
game_loop:
    LOAD  R27, R28, MMIO_VIDEO_FB_BACK_OFF   ; cambia en cada intercambio

    JAL   R31, erase_entities
    JAL   R31, update_entities
    JAL   R31, draw_entities

    JAL   R31, swap_and_wait

    ; alternar la paridad
    LI    R1, parity
    LOAD  R2, R1, 0
    XORI  R2, R2, 1
    STORE R2, R1, 0

    BRA   game_loop

; =========================================================================
; swap_and_wait - pide el intercambio y espera a que el hardware lo aplique
; =========================================================================
swap_and_wait:
    MOVI  R1, 1
    STORE R1, R28, MMIO_VIDEO_SWAP_OFF
@wait:
    LOAD  R1, R28, MMIO_VIDEO_SWAP_OFF
    BNE   R1, R0, @wait
    RET

; =========================================================================
; decode_maze - de `maze_ascii` a `tiles`, y cuenta las pastillas
;
; Salta todo byte < 32, que es el NUL y el relleno que mete `.string`.
; =========================================================================
decode_maze:
    LI    R1, maze_ascii
    ADDI  R2, R26, 0           ; destino en `tiles`
    LI    R3, tiles+1200       ; fin
    MOVI  R4, 0                ; pastillas contadas
@next:
    BGEU  R2, R3, @done
    LOADUB R5, R1, 0
    ADDI  R1, R1, 1
    MOVI  R6, 32
    BLTU  R5, R6, @next        ; relleno: no ocupa tile

    MOVI  R7, T_EMPTY
    MOVI  R6, 35               ; '#'
    BEQ   R5, R6, @wall
    MOVI  R6, 46               ; '.'
    BEQ   R5, R6, @pill
    MOVI  R6, 111              ; 'o'
    BEQ   R5, R6, @power
    BRA   @put
@wall:
    MOVI  R7, T_WALL
    BRA   @put
@pill:
    MOVI  R7, T_PILL
    ADDI  R4, R4, 1
    BRA   @put
@power:
    MOVI  R7, T_POWER
    ADDI  R4, R4, 1
@put:
    STOREB R7, R2, 0
    ADDI  R2, R2, 1
    BRA   @next
@done:
    LI    R1, pills_left
    STORE R4, R1, 0
    RET

; =========================================================================
; draw_logo - vuelca la imagen RGB565 de 320x240 en R27
; =========================================================================
draw_logo:
    LI    R1, logo_image
    ADDI  R2, R27, 0
    MOVI  R3, 0
    LI    R4, 38400            ; 320*240 px = 38400 palabras de 2 px
@copy:
    LOAD  R5, R1, 0
    STORE R5, R2, 0
    ADDI  R1, R1, 4
    ADDI  R2, R2, 4
    ADDI  R3, R3, 1
    BLT   R3, R4, @copy
    RET

; =========================================================================
; draw_maze - pinta los 1200 tiles en R27
; =========================================================================
draw_maze:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -8
    STORE R10, R29, 0          ; fila
    STORE R11, R29, 4          ; columna

    MOVI  R10, 0
@row:
    MOVI  R11, 0
@col:
    ADDI  R4, R11, 0
    ADDI  R5, R10, 0
    JAL   R31, draw_tile
    ADDI  R11, R11, 1
    MOVI  R1, COLS
    BLT   R11, R1, @col
    ADDI  R10, R10, 1
    MOVI  R1, ROWS
    BLT   R10, R1, @row

    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    ADDI  R29, R29, 8
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; draw_tile - pinta el tile (R4=columna, R5=fila) en R27
;
; Hoja: no llama a nadie, asi que no toca la pila.
; =========================================================================
draw_tile:
    ; codigo de tile = tiles[fila*40 + columna]
    SHLI  R1, R5, 5            ; fila*32
    SHLI  R2, R5, 3            ; fila*8
    ADD   R1, R1, R2           ; fila*40
    ADD   R1, R1, R4
    ADD   R1, R1, R26
    LOADUB R6, R1, 0           ; R6 = codigo

    ; direccion = R27 + fila*5120 + columna*16
    SHLI  R1, R5, 12
    SHLI  R2, R5, 10
    ADD   R1, R1, R2
    SHLI  R2, R4, 4
    ADD   R1, R1, R2
    ADD   R7, R1, R27          ; R7 = esquina superior izquierda

    ; color de fondo del tile: azul si es muro, negro si no
    LI    R8, C_BLACK_W
    MOVI  R1, T_WALL
    BNE   R6, R1, @fill
    LI    R8, C_WALL_W
@fill:
    ; 8 lineas de 4 palabras
    ADDI  R2, R7, 0
    MOVI  R3, 0
    MOVI  R9, 8
@line:
    STORE R8, R2, 0
    STORE R8, R2, 4
    STORE R8, R2, 8
    STORE R8, R2, 12
    ADDI  R2, R2, PITCH
    ADDI  R3, R3, 1
    BLT   R3, R9, @line

    ; La pastilla va encima del fondo negro ya escrito.
    MOVI  R1, T_PILL
    BEQ   R6, R1, @pill
    MOVI  R1, T_POWER
    BEQ   R6, R1, @power
    RET

@pill:
    ; cuadrado de 2x2 centrado: pixeles (3,3) a (4,4)
    LI    R8, C_PILL
    ADDI  R2, R7, 1926        ; (3,3): 3*640 + 3*2
    STOREH R8, R2, 0
    STOREH R8, R2, 2
    STOREH R8, R2, PITCH
    STOREH R8, R2, PITCH+2
    RET

@power:
    ; cuadrado de 4x4 centrado: pixeles (2,2) a (5,5)
    LI    R8, C_PILL
    ADDI  R2, R7, 1284        ; (2,2): 2*640 + 2*2
    MOVI  R3, 0
    MOVI  R9, 4
@prow:
    STOREH R8, R2, 0
    STOREH R8, R2, 2
    STOREH R8, R2, 4
    STOREH R8, R2, 6
    ADDI  R2, R2, PITCH
    ADDI  R3, R3, 1
    BLT   R3, R9, @prow
    RET

; =========================================================================
; erase_entities - repinta desde `tiles` los 2x2 tiles donde cada entidad
;                  se dibujo la ultima vez EN ESTE MISMO BUFFER
; =========================================================================
erase_entities:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -8
    STORE R10, R29, 0
    STORE R11, R29, 4

    LI    R1, parity
    LOAD  R11, R1, 0           ; 0 -> E_PX0, 1 -> E_PX1

    MOVI  R10, 0
@ent:
    MOVI  R1, E_SIZE
    MUL   R1, R10, R1
    ADD   R12, R25, R1         ; R12 = &ent[i]

    BNE   R11, R0, @slot1
    LOAD  R4, R12, E_PX0
    LOAD  R5, R12, E_PY0
    BRA   @have
@slot1:
    LOAD  R4, R12, E_PX1
    LOAD  R5, R12, E_PY1
@have:
    SHRI  R4, R4, 3            ; columna del tile
    SHRI  R5, R5, 3            ; fila
    JAL   R31, erase_block

    ADDI  R10, R10, 1
    MOVI  R1, NENT
    BLT   R10, R1, @ent

    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    ADDI  R29, R29, 8
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; erase_block - repinta los 2x2 tiles con esquina en (R4=columna, R5=fila)
;
; La columna se envuelve porque en la fila del tunel una entidad puede estar
; en la columna 39, y entonces el tile de al lado es el 0.
; =========================================================================
erase_block:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -12
    STORE R10, R29, 0
    STORE R11, R29, 4
    STORE R12, R29, 8

    ADDI  R10, R4, 0
    ADDI  R11, R5, 0

    MOVI  R12, 0
@row:
    ADD   R5, R11, R12
    MOVI  R1, ROWS
    BGE   R5, R1, @nextrow     ; fuera de pantalla por abajo: nada que borrar

    ADDI  R4, R10, 0
    JAL   R31, draw_tile

    ADDI  R4, R10, 1
    MOVI  R1, COLS
    BLT   R4, R1, @second
    ADDI  R4, R4, -40        ; envuelve por el tunel
@second:
    ADD   R5, R11, R12
    JAL   R31, draw_tile
@nextrow:
    ADDI  R12, R12, 1
    MOVI  R1, 2
    BLT   R12, R1, @row

    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    LOAD  R12, R29, 8
    ADDI  R29, R29, 12
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; draw_entities - dibuja las cinco y anota donde, en la mitad que toque
; =========================================================================
draw_entities:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -8
    STORE R10, R29, 0
    STORE R11, R29, 4

    LI    R1, parity
    LOAD  R11, R1, 0

    MOVI  R10, 0
@ent:
    MOVI  R1, E_SIZE
    MUL   R1, R10, R1
    ADD   R12, R25, R1

    LOAD  R4, R12, E_X
    LOAD  R5, R12, E_Y
    LOAD  R6, R12, E_COL
    LOAD  R7, R12, E_BM
    JAL   R31, draw_sprite

    ; anotar la posicion para poder borrarla dentro de dos frames
    LOAD  R4, R12, E_X
    LOAD  R5, R12, E_Y
    BNE   R11, R0, @slot1
    STORE R4, R12, E_PX0
    STORE R5, R12, E_PY0
    BRA   @next
@slot1:
    STORE R4, R12, E_PX1
    STORE R5, R12, E_PY1
@next:
    ADDI  R10, R10, 1
    MOVI  R1, NENT
    BLT   R10, R1, @ent

    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    ADDI  R29, R29, 8
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; draw_sprite - bitmap 8x8 de R7, color R6, esquina en (R4=x, R5=y) de R27
;
; Un bit a 1 pinta; un 0 deja ver el laberinto de debajo. Hoja.
;
; Se queda dentro de R1-R9 a proposito. R10, R11 y R12 son de quien llama en
; todo el programa, y aqui eso no es una formalidad: `draw_entities` lleva en
; R10 el indice de la entidad que esta dibujando, asi que una rutina que lo
; use de temporal deja ese bucle sin condicion de salida.
; =========================================================================
draw_sprite:
    ; direccion = R27 + y*640 + x*2
    SHLI  R1, R5, 9            ; y*512
    SHLI  R2, R5, 7            ; y*128
    ADD   R1, R1, R2           ; y*640
    SHLI  R2, R4, 1
    ADD   R1, R1, R2
    ADD   R1, R1, R27

    MOVI  R5, 8                ; lado del sprite; x e y ya no hacen falta
    MOVI  R3, 0                ; fila del sprite
@row:
    LOADUB R8, R7, 0           ; los 8 bits de esta fila
    ADDI  R7, R7, 1
    ADDI  R2, R1, 0            ; puntero de escritura
    MOVI  R9, 0                ; columna
@col:
    MOVI  R4, 0x80
    SHR   R4, R4, R9           ; mascara del bit de esta columna
    AND   R4, R4, R8
    BEQ   R4, R0, @skip
    STOREH R6, R2, 0
@skip:
    ADDI  R2, R2, 2
    ADDI  R9, R9, 1
    BLT   R9, R5, @col

    ADDI  R1, R1, PITCH
    ADDI  R3, R3, 1
    BLT   R3, R5, @row
    RET

; =========================================================================
; update_entities - mueve a los cinco, come pastillas y mira colisiones
; =========================================================================
update_entities:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -8
    STORE R10, R29, 0
    STORE R11, R29, 4

    MOVI  R10, 0
@ent:
    MOVI  R1, E_SIZE
    MUL   R1, R10, R1
    ADD   R11, R25, R1         ; R11 = &ent[i]

    ; ---- decidir, pero solo en el centro de un tile ----
    LOAD  R4, R11, E_X
    LOAD  R5, R11, E_Y
    ANDI  R1, R4, 7
    BNE   R1, R0, @move
    ANDI  R1, R5, 7
    BNE   R1, R0, @move

    ; Alineada: Pac-Man come lo que haya en este tile antes de elegir.
    BNE   R10, R0, @ghost
    JAL   R31, eat_pill
    ADDI  R4, R11, 0
    JAL   R31, choose_pac
    BRA   @move
@ghost:
    ADDI  R4, R11, 0
    JAL   R31, choose_ghost

@move:
    ; ---- avanzar 2 px y envolver por el tunel ----
    LOAD  R4, R11, E_X
    LOAD  R5, R11, E_Y
    LOAD  R6, R11, E_DX
    LOAD  R7, R11, E_DY
    ADD   R4, R4, R6
    ADD   R5, R5, R7

    BGE   R4, R0, @xhigh
    MOVI  R4, SCR_W-TILE       ; salio por la izquierda: aparece a la derecha
    BRA   @xok
@xhigh:
    MOVI  R1, SCR_W-TILE
    BLT   R1, R4, @wrapr
    BRA   @xok
@wrapr:
    MOVI  R4, 0
@xok:
    STORE R4, R11, E_X
    STORE R5, R11, E_Y

    ADDI  R10, R10, 1
    MOVI  R1, NENT
    BLT   R10, R1, @ent

    JAL   R31, check_collision

    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    ADDI  R29, R29, 8
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; eat_pill - si el tile de Pac-Man tiene pastilla, se la come
;
; R11 = &ent[0]. Al llegar a cero se repone el laberinto entero.
; =========================================================================
eat_pill:
    ADDI  R29, R29, -4
    STORE R31, R29, 0

    LOAD  R4, R11, E_X
    LOAD  R5, R11, E_Y
    SHRI  R4, R4, 3
    SHRI  R5, R5, 3
    SHLI  R1, R5, 5
    SHLI  R2, R5, 3
    ADD   R1, R1, R2
    ADD   R1, R1, R4
    ADD   R1, R1, R26          ; &tiles[fila*40+col]
    LOADUB R2, R1, 0

    MOVI  R3, T_PILL
    BEQ   R2, R3, @eat
    MOVI  R3, T_POWER
    BEQ   R2, R3, @eat
    BRA   @out

@eat:
    STOREB R0, R1, 0           ; el tile pasa a vacio
    LI    R3, pills_left
    LOAD  R4, R3, 0
    ADDI  R4, R4, -1
    STORE R4, R3, 0
    BNE   R4, R0, @out

    ; ---- laberinto limpio: se repone ----
    ; Hay que repintarlo en los DOS buffers aqui mismo. Dejarlo al borrado
    ; incremental no serviria: ese solo toca los 2x2 tiles bajo las entidades,
    ; y las pastillas repuestas estan por toda la pantalla.
    JAL   R31, decode_maze
    JAL   R31, reset_entities
    ADDI  R29, R29, -4
    STORE R27, R29, 0
    LI    R27, FB0
    JAL   R31, draw_maze
    LI    R27, FB1
    JAL   R31, draw_maze
    LOAD  R27, R29, 0
    ADDI  R29, R29, 4

@out:
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; is_wall - R1 = 1 si el tile (R4=columna, R5=fila) es muro
;
; Envuelve la columna y trata como muro todo lo que se salga por arriba o por
; abajo, que es lo que impide que una entidad se escape del laberinto.
; =========================================================================
is_wall:
    MOVI  R1, 1                ; por defecto, muro
    BLT   R5, R0, @out
    MOVI  R2, ROWS
    BGE   R5, R2, @out

    ADDI  R3, R4, 0
    BGE   R3, R0, @hi
    ADDI  R3, R3, COLS
    BRA   @have
@hi:
    MOVI  R2, COLS
    BLT   R3, R2, @have
    ADDI  R3, R3, -40
@have:
    SHLI  R1, R5, 5
    SHLI  R2, R5, 3
    ADD   R1, R1, R2
    ADD   R1, R1, R3
    ADD   R1, R1, R26
    LOADUB R2, R1, 0
    MOVI  R1, 0
    MOVI  R3, T_WALL
    BNE   R2, R3, @out
    MOVI  R1, 1
@out:
    RET

; =========================================================================
; rng_next - xorshift32, R1 = siguiente valor
;
; El mismo generador que usa `starfield`. Nunca devuelve cero porque la
; semilla no lo es y xorshift no puede caer en el.
; =========================================================================
rng_next:
    LI    R2, seed_rng
    LOAD  R1, R2, 0
    SHLI  R3, R1, 13
    XOR   R1, R1, R3
    SHRI  R3, R1, 17
    XOR   R1, R1, R3
    SHLI  R3, R1, 5
    XOR   R1, R1, R3
    STORE R1, R2, 0
    RET

; =========================================================================
; choose_ghost - direccion al azar entre las que no son muro (R4 = &entidad)
;
; No se permite dar media vuelta, que es lo que hace que un fantasma recorra
; el laberinto en vez de temblar en el sitio. La excepcion es un callejon sin
; salida: alli la marcha atras es la unica salida, y el laberinto tiene ocho.
; =========================================================================
choose_ghost:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -16
    STORE R10, R29, 0
    STORE R11, R29, 4
    STORE R12, R29, 8
    STORE R4,  R29, 12

    ADDI  R10, R4, 0           ; R10 = &entidad
    LOAD  R6, R10, E_DX
    LOAD  R7, R10, E_DY

    ; Las cuatro direcciones, en `dir_table` como pares (dx, dy).
    LI    R11, cand            ; buffer de indices validos
    MOVI  R12, 0               ; cuantos van

    MOVI  R9, 0
@try:
    LI    R1, dir_table
    SHLI  R2, R9, 3
    ADD   R1, R1, R2
    LOAD  R3, R1, 0            ; dx candidato
    LOAD  R8, R1, 4            ; dy candidato

    ; descartar la marcha atras: (dx,dy) == -(actual)
    ADD   R2, R3, R6
    BNE   R2, R0, @notback
    ADD   R2, R8, R7
    BNE   R2, R0, @notback
    BRA   @skip
@notback:
    ; el tile de destino: la direccion en pasos de 2 px, o sea signo
    LOAD  R4, R10, E_X
    LOAD  R5, R10, E_Y
    SHRI  R4, R4, 3
    SHRI  R5, R5, 3
    SARI  R2, R3, 1            ; dx/2 -> -1, 0 o 1
    ADD   R4, R4, R2
    SARI  R2, R8, 1
    ADD   R5, R5, R2
    ADDI  R29, R29, -8
    STORE R9, R29, 0
    STORE R3, R29, 4
    JAL   R31, is_wall
    LOAD  R9, R29, 0
    LOAD  R3, R29, 4
    ADDI  R29, R29, 8
    BNE   R1, R0, @skip

    STORE R9, R11, 0           ; guardar el indice de direccion
    ADDI  R11, R11, 4
    ADDI  R12, R12, 1
@skip:
    ADDI  R9, R9, 1
    MOVI  R1, 4
    BLT   R9, R1, @try

    BNE   R12, R0, @pick

    ; Callejon sin salida: la unica salida es volver por donde vino.
    SUB   R1, R0, R6
    STORE R1, R10, E_DX
    SUB   R1, R0, R7
    STORE R1, R10, E_DY
    BRA   @out

@pick:
    JAL   R31, rng_next
    ; xorshift puede devolver negativos; REMU lo trata como sin signo, que es
    ; justo lo que hace falta para indexar.
    REMU  R1, R1, R12
    LI    R2, cand
    SHLI  R3, R1, 2
    ADD   R2, R2, R3
    LOAD  R9, R2, 0            ; indice de direccion elegido

    LI    R1, dir_table
    SHLI  R2, R9, 3
    ADD   R1, R1, R2
    LOAD  R3, R1, 0
    LOAD  R8, R1, 4
    STORE R3, R10, E_DX
    STORE R8, R10, E_DY

@out:
    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    LOAD  R12, R29, 8
    ADDI  R29, R29, 16
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; choose_pac - hacia las pastillas, lejos de los fantasmas (R4 = &entidad)
;
; Dos mecanismos, y cada uno resuelve lo que el otro no puede:
;
;   - **Las pastillas, por recorrido en anchura** (`bfs_dir`), que devuelve el
;     primer paso del camino mas corto hasta la pastilla mas cercana que quede
;     EN TODO el laberinto.
;   - **Los fantasmas, mirando 8 tiles en linea recta** (`score_dir`), que
;     castiga una direccion tanto mas cuanto mas cerca este el fantasma.
;
; La primera version puntuaba tambien las pastillas con ese vistazo de 8
; tiles, y estaba mal de una forma que no se ve en una captura: en cuanto
; Pac-Man limpiaba su rincon, ninguna direccion veia nada, todas empataban a
; cero, ganaba siempre la primera y se quedaba dando vueltas por el mismo
; pasillo vacio para siempre. Medido: las pastillas se congelaban en 167 de
; 468 y ya no bajaban en 12 000 intercambios mas. Un vistazo local no puede
; salir de un minimo local; por eso las pastillas necesitan busqueda global y
; los fantasmas no.
;
; Los pesos: acertar la direccion del recorrido vale +100, y un fantasma suma
; hasta -480 si esta pegado. Asi un fantasma cerca desvia a Pac-Man de su
; camino, pero uno lejano no le hace abandonarlo.
;
; No es la IA del juego original --- no hay modos, ni objetivos por fantasma ---
; pero basta para que limpie el laberinto y para que se le vea huir.
; =========================================================================
choose_pac:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -28
    STORE R10, R29, 0
    STORE R11, R29, 4
    STORE R12, R29, 8
    ; 12: mejor puntuacion   16: mejor direccion   20: direccion en curso
    ; 24: direccion que pide el recorrido en anchura

    ADDI  R10, R4, 0           ; R10 = &entidad
    LI    R1, -100000
    STORE R1, R29, 12
    MOVI  R1, -1
    STORE R1, R29, 16

    JAL   R31, bfs_dir         ; R1 = direccion a la pastilla mas cercana, o -1
    STORE R1, R29, 24

    MOVI  R9, 0
@try:
    STORE R9, R29, 20

    LI    R1, dir_table
    SHLI  R2, R9, 3
    ADD   R1, R1, R2
    LOAD  R3, R1, 0            ; dx candidato
    LOAD  R8, R1, 4            ; dy candidato

    SARI  R11, R3, 1           ; paso en tiles: -1, 0 o 1
    SARI  R12, R8, 1

    ; el primer tile ya tiene que ser transitable
    LOAD  R4, R10, E_X
    LOAD  R5, R10, E_Y
    SHRI  R4, R4, 3
    SHRI  R5, R5, 3
    ADD   R4, R4, R11
    ADD   R5, R5, R12
    JAL   R31, is_wall
    BNE   R1, R0, @skip

    JAL   R31, score_dir       ; R1 = castigo por los fantasmas de esa linea

    ; premio si es la direccion que pide el recorrido en anchura
    LOAD  R2, R29, 24
    LOAD  R3, R29, 20
    BNE   R2, R3, @noguide
    ADDI  R1, R1, 100
@noguide:
    ; Penalizacion pequena por dar media vuelta. Aqui la marcha atras SI es
    ; candidata --- si la pastilla mas cercana esta detras, hay que volver ---
    ; pero sin este empujon Pac-Man tiembla en el sitio cuando dos direcciones
    ; puntuan igual.
    LOAD  R6, R10, E_DX
    LOAD  R7, R10, E_DY
    LI    R2, dir_table
    LOAD  R3, R29, 20
    SHLI  R4, R3, 3
    ADD   R2, R2, R4
    LOAD  R4, R2, 0
    LOAD  R5, R2, 4
    ADD   R4, R4, R6
    BNE   R4, R0, @notback
    ADD   R5, R5, R7
    BNE   R5, R0, @notback
    ADDI  R1, R1, -10
@notback:

    LOAD  R2, R29, 12
    BGE   R2, R1, @skip        ; empate: gana la primera, asi no oscila
    STORE R1, R29, 12
    LOAD  R9, R29, 20
    STORE R9, R29, 16

@skip:
    LOAD  R9, R29, 20
    ADDI  R9, R9, 1
    MOVI  R1, 4
    BLT   R9, R1, @try

    LOAD  R9, R29, 16
    BLT   R9, R0, @deadend

    LI    R1, dir_table
    SHLI  R2, R9, 3
    ADD   R1, R1, R2
    LOAD  R3, R1, 0
    LOAD  R8, R1, 4
    STORE R3, R10, E_DX
    STORE R8, R10, E_DY
    BRA   @out

@deadend:
    ; Encerrado por los cuatro lados: no puede pasar en este laberinto, pero
    ; dejarse la rama significaria mantener la direccion contra un muro.
    LOAD  R6, R10, E_DX
    LOAD  R7, R10, E_DY
    SUB   R1, R0, R6
    STORE R1, R10, E_DX
    SUB   R1, R0, R7
    STORE R1, R10, E_DY

@out:
    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    LOAD  R12, R29, 8
    ADDI  R29, R29, 28
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; score_dir - castigo por los fantasmas que se ven hacia (R11, R12) desde ent[0]
;
; Mira hasta 8 tiles en linea recta y para al chocar con una pared, porque un
; fantasma al otro lado de un muro no es una amenaza. Por cada uno que
; encuentra resta 60 por el peso de la distancia (8 pegado, 1 al fondo).
;
; R1 = puntuacion, siempre <= 0. No toca R10, R11 ni R12.
; =========================================================================
score_dir:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -16
    ; 0: acumulado   4: paso k   8: columna   12: fila

    STORE R0, R29, 0
    MOVI  R1, 1
    STORE R1, R29, 4

    LOAD  R4, R25, E_X
    LOAD  R5, R25, E_Y
    SHRI  R4, R4, 3
    SHRI  R5, R5, 3
    STORE R4, R29, 8
    STORE R5, R29, 12

@step:
    LOAD  R4, R29, 8
    LOAD  R5, R29, 12
    ADD   R4, R4, R11
    ADD   R5, R5, R12

    ; envolver la columna, igual que hace is_wall
    BGE   R4, R0, @hi
    ADDI  R4, R4, COLS
    BRA   @have
@hi:
    MOVI  R1, COLS
    BLT   R4, R1, @have
    ADDI  R4, R4, -40
@have:
    STORE R4, R29, 8
    STORE R5, R29, 12

    JAL   R31, is_wall
    BNE   R1, R0, @done        ; la pared corta la vista

    LOAD  R4, R29, 8
    LOAD  R5, R29, 12
    LOAD  R6, R29, 4           ; k
    MOVI  R7, 9
    SUB   R7, R7, R6           ; peso 8..1, mas cerca pesa mas

    ; ---- algun fantasma en este tile? ----
    MOVI  R8, 1
@geach:
    MOVI  R1, E_SIZE
    MUL   R1, R8, R1
    ADD   R1, R25, R1
    LOAD  R2, R1, E_X
    LOAD  R3, R1, E_Y
    SHRI  R2, R2, 3
    SHRI  R3, R3, 3
    BNE   R2, R4, @gnext
    BNE   R3, R5, @gnext
    LOAD  R1, R29, 0
    MOVI  R3, 60
    MUL   R3, R7, R3
    SUB   R1, R1, R3
    STORE R1, R29, 0
@gnext:
    ADDI  R8, R8, 1
    MOVI  R1, NENT
    BLT   R8, R1, @geach

    LOAD  R6, R29, 4
    ADDI  R6, R6, 1
    STORE R6, R29, 4
    MOVI  R1, 9
    BLT   R6, R1, @step

@done:
    LOAD  R1, R29, 0
    ADDI  R29, R29, 16
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; bfs_dir - primer paso hacia la pastilla mas cercana. R1 = direccion, o -1
;
; Recorrido en anchura sobre la rejilla de tiles desde donde esta Pac-Man. La
; primera pastilla que sale de la cola es la mas cercana EN NUMERO DE TILES
; POR PASILLO, que es la distancia que importa: la distancia en linea recta
; manda a Pac-Man contra una pared y ahi se queda.
;
; El truco para saber por donde empezar a andar: `visited` no guarda un "ya
; estuve aqui" sino **la direccion del primer paso** del camino que llego a
; ese tile (1..4, con 0 como "sin visitar"). Se propaga sin cambiar al
; expandir, asi que al encontrar la pastilla la respuesta ya esta escrita y no
; hace falta reconstruir el camino hacia atras.
;
; La marcha atras no se excluye: si lo que queda esta detras, hay que volver.
; Y no puede hacer temblar a Pac-Man, porque cada paso le acerca de verdad a
; una pastilla que existe.
;
; Coste: en cuanto hay una pastilla cerca --- casi siempre --- la cola se vacia
; en unos pocos tiles. El caso malo es el final de la pantalla, con las
; ultimas pastillas lejos, y aun asi son 1200 tiles como mucho, una vez cada
; cuatro frames.
; =========================================================================
bfs_dir:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    ADDI  R29, R29, -12
    STORE R10, R29, 0
    STORE R11, R29, 4
    STORE R12, R29, 8

    ; Limpiar `visited` de una pasada. Son 1200 bytes, o sea 300 palabras.
    LI    R1, visited
    LI    R2, visited+1200
@clear:
    STORE R0, R1, 0
    ADDI  R1, R1, 4
    BLTU  R1, R2, @clear

    MOVI  R10, 0               ; cabeza de la cola
    MOVI  R11, 0               ; cola de la cola

    ; Un elemento de la cola es (fila << 8) | columna. Cabe de sobra y evita
    ; dividir por 40 para recuperar la fila.
    LOAD  R4, R25, E_X
    LOAD  R5, R25, E_Y
    SHRI  R4, R4, 3
    SHRI  R5, R5, 3
    SHLI  R12, R5, 8
    OR    R12, R12, R4

    ; ---- sembrar con los cuatro vecinos, cada uno con su propia marca ----
    MOVI  R9, 0
@seed:
    ADDI  R8, R9, 1            ; marca = direccion + 1
    JAL   R31, bfs_push
    ADDI  R9, R9, 1
    MOVI  R1, 4
    BLT   R9, R1, @seed

@pop:
    BGE   R10, R11, @none

    LI    R1, bfsq
    SHLI  R2, R10, 2
    ADD   R1, R1, R2
    LOAD  R12, R1, 0
    ADDI  R10, R10, 1

    SHRI  R5, R12, 8           ; fila
    ANDI  R4, R12, 0xFF        ; columna
    SHLI  R1, R5, 5
    SHLI  R2, R5, 3
    ADD   R1, R1, R2
    ADD   R1, R1, R4           ; indice de tile

    ADD   R2, R1, R26
    LOADUB R3, R2, 0           ; que hay en este tile
    LI    R2, visited
    ADD   R2, R2, R1
    LOADUB R8, R2, 0           ; marca heredada por este tile

    MOVI  R6, T_PILL
    BEQ   R3, R6, @found
    MOVI  R6, T_POWER
    BEQ   R3, R6, @found

    ; no hay pastilla: expandir a los cuatro vecinos con la misma marca
    MOVI  R9, 0
@exp:
    JAL   R31, bfs_push
    ADDI  R9, R9, 1
    MOVI  R1, 4
    BLT   R9, R1, @exp
    BRA   @pop

@found:
    ADDI  R1, R8, -1           ; la marca era direccion + 1
    BRA   @out
@none:
    MOVI  R1, -1

@out:
    LOAD  R10, R29, 0
    LOAD  R11, R29, 4
    LOAD  R12, R29, 8
    ADDI  R29, R29, 12
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; bfs_push - encola el vecino de R12 en la direccion R9, con la marca R8
;
; R12 = (fila << 8) | columna del tile de partida. Avanza R11 (la cola) si
; encola. No toca R8, R9, R10 ni R12; usa R1-R7.
;
; La columna se envuelve, asi que el recorrido cruza el tunel igual que lo
; cruzan las entidades. Si no lo hiciera, Pac-Man daria la vuelta entera al
; laberinto para llegar a algo que tiene a un paso por el otro lado.
; =========================================================================
bfs_push:
    SHRI  R5, R12, 8           ; fila
    ANDI  R4, R12, 0xFF        ; columna

    LI    R1, dir_table
    SHLI  R2, R9, 3
    ADD   R1, R1, R2
    LOAD  R3, R1, 0
    LOAD  R6, R1, 4
    SARI  R3, R3, 1            ; paso en tiles
    SARI  R6, R6, 1
    ADD   R4, R4, R3
    ADD   R5, R5, R6

    ; fuera por arriba o por abajo: no hay tile
    BLT   R5, R0, @out
    MOVI  R1, ROWS
    BGE   R5, R1, @out

    BGE   R4, R0, @hi
    ADDI  R4, R4, COLS
    BRA   @have
@hi:
    MOVI  R1, COLS
    BLT   R4, R1, @have
    ADDI  R4, R4, -40
@have:
    SHLI  R1, R5, 5
    SHLI  R2, R5, 3
    ADD   R1, R1, R2
    ADD   R1, R1, R4           ; indice de tile

    ADD   R2, R1, R26
    LOADUB R3, R2, 0
    MOVI  R7, T_WALL
    BEQ   R3, R7, @out         ; los muros no se atraviesan

    LI    R2, visited
    ADD   R2, R2, R1
    LOADUB R3, R2, 0
    BNE   R3, R0, @out         ; ya alcanzado, y por un camino mas corto

    STOREB R8, R2, 0

    LI    R2, bfsq
    SHLI  R3, R11, 2
    ADD   R2, R2, R3
    SHLI  R1, R5, 8
    OR    R1, R1, R4
    STORE R1, R2, 0
    ADDI  R11, R11, 1
@out:
    RET

; =========================================================================
; check_collision - si un fantasma alcanza a Pac-Man, todos a sus casillas
;
; Solo se reposiciona: las pastillas comidas siguen comidas, asi que la
; partida avanza igual y la demo no se queda en bucle.
; =========================================================================
check_collision:
    LOAD  R4, R25, E_X
    LOAD  R5, R25, E_Y

    MOVI  R8, 1
@each:
    MOVI  R1, E_SIZE
    MUL   R1, R8, R1
    ADD   R1, R25, R1
    LOAD  R2, R1, E_X
    LOAD  R3, R1, E_Y

    SUB   R2, R2, R4
    BGE   R2, R0, @absx
    SUB   R2, R0, R2
@absx:
    MOVI  R6, 6
    BGE   R2, R6, @next

    SUB   R3, R3, R5
    BGE   R3, R0, @absy
    SUB   R3, R0, R3
@absy:
    BLT   R3, R6, @hit

@next:
    ADDI  R8, R8, 1
    MOVI  R1, NENT
    BLT   R8, R1, @each
    RET

@hit:
    ADDI  R29, R29, -4
    STORE R31, R29, 0
    JAL   R31, reset_entities
    LOAD  R31, R29, 0
    ADDI  R29, R29, 4
    RET

; =========================================================================
; reset_entities - las cinco a sus casillas de salida
;
; **No toca E_PX0/E_PY0 ni E_PX1/E_PY1**, y eso es justo lo que hace que la
; demo no se llene de fantasmas. Reposicionar es teletransportar: los sprites
; que ya estan pintados en los dos buffers siguen ahi, y las unicas dos
; direcciones que saben donde estan son esas. Ponerlas a "nada que borrar" deja
; un fantasma clavado en la pantalla por cada colision, para siempre.
;
; En el arranque valen cero, que apunta al tile (0,0). Da igual: el borrado
; repinta desde `tiles`, asi que borrar donde no habia nada solo vuelve a
; pintar la pared que ya estaba.
; =========================================================================
reset_entities:
    LI    R1, spawn_table
    ADDI  R2, R25, 0           ; destino: ent[0]
    MOVI  R3, 0
@each:
    LOAD  R4, R1, 0            ; columna de salida
    LOAD  R5, R1, 4            ; fila
    LOAD  R6, R1, 8            ; color
    LOAD  R7, R1, 12           ; bitmap
    ADDI  R1, R1, 16

    SHLI  R4, R4, 3            ; a pixeles
    SHLI  R5, R5, 3
    STORE R4, R2, E_X
    STORE R5, R2, E_Y
    STORE R6, R2, E_COL
    STORE R7, R2, E_BM

    ; Todas arrancan yendo a la izquierda. No es arbitrario: la fila 13 es el
    ; tunel y esta despejada a lo ancho, asi que ninguna empieza contra un muro
    ; y la primera decision cae en el siguiente tile.
    MOVI  R8, -2
    STORE R8, R2, E_DX
    STORE R0, R2, E_DY

    ADDI  R2, R2, E_SIZE
    ADDI  R3, R3, 1
    MOVI  R9, NENT
    BLT   R3, R9, @each
    RET

; =========================================================================
.rodata

; Las cuatro direcciones en pasos de 2 px: derecha, abajo, izquierda, arriba.
dir_table:
    .word  2,  0
    .word  0,  2
    .word -2,  0
    .word  0, -2

; Casilla de salida de cada entidad: columna, fila, color, bitmap.
; Pac-Man abajo, los cuatro fantasmas repartidos por la fila del tunel.
spawn_table:
    .word 18, 27, C_PAC, pac_bm
    .word 12, 13, C_G0,  ghost_bm
    .word 17, 13, C_G1,  ghost_bm
    .word 22, 13, C_G2,  ghost_bm
    .word 27, 13, C_G3,  ghost_bm

; Un byte por fila, el bit 7 es el pixel de la izquierda.
pac_bm:
    .byte 0b00111100
    .byte 0b01111110
    .byte 0b11111111
    .byte 0b11111100
    .byte 0b11111000
    .byte 0b11111100
    .byte 0b01111110
    .byte 0b00111100

ghost_bm:
    .byte 0b00111100
    .byte 0b01111110
    .byte 0b11011011
    .byte 0b11011011
    .byte 0b11111111
    .byte 0b11111111
    .byte 0b11111111
    .byte 0b10100101

; El laberinto. 30 filas de 40 columnas, simetrico izquierda-derecha.
;   '#' muro    '.' pastilla    'o' pastilla grande    ' ' vacio
; La fila 13 esta abierta por los dos lados: es el tunel, y el codigo envuelve
; la columna para que se pueda cruzar.
maze_ascii:
    .string "########################################"
    .string "#..................##..................#"
    .string "#.####.#####.#####.##.#####.#####.####.#"
    .string "#o####.#####.#####.##.#####.#####.####o#"
    .string "#.####.#####.#####.##.#####.#####.####.#"
    .string "#......................................#"
    .string "#.####.##.####################.##.####.#"
    .string "#.####.##.####################.##.####.#"
    .string "#......##..........##..........##......#"
    .string "######.#####.##############.#####.######"
    .string "######.#####.##############.#####.######"
    .string "######.##..........##..........##.######"
    .string "######.##.####..########..####.##.######"
    .string "..........#........##........#.........."
    .string "######.##.#........##........#.##.######"
    .string "######.##.####################.##.######"
    .string "######.##..........##..........##.######"
    .string "######.##.####################.##.######"
    .string "#..................##..................#"
    .string "#.####.#####.#####.##.#####.#####.####.#"
    .string "#.####.#####.#####.##.#####.#####.####.#"
    .string "#o..##.............##.............##..o#"
    .string "###.##.##.####################.##.##.###"
    .string "###.##.##.####################.##.##.###"
    .string "#......##....#####.##.#####....##......#"
    .string "#.##########.#####.##.#####.##########.#"
    .string "#.##########.#####.##.#####.##########.#"
    .string "#..................##..................#"
    .string "#..................##..................#"
    .string "########################################"

logo_image:
    .incbin "minigpu-small.bin"

; =========================================================================
.bss

tiles:      .space 1200        ; 40*30, un byte por tile
ent:        .space 200         ; 5 entidades de 40 bytes
cand:       .space 16          ; direcciones validas de un fantasma

; Del recorrido en anchura. `visited` guarda la direccion del primer paso, no
; un booleano; `bfsq` no puede desbordar porque un tile se encola solo la vez
; que se marca, y solo hay 1200.
visited:    .space 1200
bfsq:       .space 4800

seed_rng:   .space 4
pills_left: .space 4
parity:     .space 4

            .space 512
stack_top:
