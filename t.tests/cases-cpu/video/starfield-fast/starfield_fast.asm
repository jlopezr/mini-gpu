; ============================================================
; starfield_fast.asm - el campo de estrellas sin borrar la pantalla entera
;
; Mismo campo que `starfield.asm`, pixel a pixel: mismo xorshift, mismo orden
; de tiradas, misma proyeccion, mismos cortes de brillo. Lo unico que cambia es
; como se limpia el frame anterior.
;
; Por que
; -------
;
; En `starfield.asm` el reparto del frame es este:
;
;     borrar el buffer entero    115 200 instrucciones   (38 400 palabras x 3)
;     las 256 estrellas            ~6 400 instrucciones
;
; O sea que el 95 % del trabajo es pintar de negro 38 400 palabras para volver
; a encender 256 pixeles. Borrando solo esos 256 el frame baja a unas 9 000
; instrucciones: trece veces menos, y deja de mandar el borrado para mandar el
; vsync.
;
; El buffer trasero NO es el frame anterior
; -----------------------------------------
;
; Aqui esta la trampa, y es la razon por la que `bounce.asm` decidio repintar
; entero. Con doble buffer, lo que hay en el buffer trasero no es lo que se vio
; el frame pasado sino lo de **hace dos**, porque los buffers se alternan. Asi
; que no se puede borrar la posicion anterior de la estrella: hay que borrar la
; de hace dos frames, que es la que se escribio en este mismo buffer.
;
; Por eso cada estrella guarda dos direcciones en vez de una:
;
;     registro: x, y, z, a0, a1        ; 3 palabras -> 5, o sea 20 bytes
;
;     a0 = donde se pinto el frame pasado   (en el OTRO buffer)
;     a1 = donde se pinto hace dos frames   (en ESTE buffer)
;
; Cada frame: borrar a1, pintar en la direccion nueva, y rotar a1 <- a0,
; a0 <- nueva. El cero hace de centinela: "este frame no se pinto nada", que
; pasa cuando la estrella quedo recortada o acababa de renacer. Sin centinela
; se borraria el pixel (0,0) del framebuffer, que no es de nadie.
;
; Dos pasadas, y no una
; ---------------------
;
; Los borrados van TODOS antes que los dibujos, en una pasada aparte. Si se
; entrelazasen --borrar y dibujar estrella por estrella-- el borrado de la
; estrella 200 podria apagar el pixel que acaba de encender la 30, cuando las
; dos caen en el mismo sitio. Con dos pasadas, el estado del buffer despues de
; la primera es exactamente "todo negro", igual que en `starfield.asm`, y de
; ahi que los dos programas den el frame identico. Esa igualdad es lo que
; demuestra que la contabilidad de los dos buffers esta bien: es lo unico
; dificil de ver a ojo aqui.
;
; La primera pasada cuesta unas 1 500 instrucciones, asi que el ahorro se
; mantiene.
;
; Al arrancar hay que borrar los DOS buffers una vez, cosa que en la version
; lenta salia gratis del borrado por frame. Son contiguos --0x01000000 y
; 0x01025800, 153 600 bytes cada uno-- asi que es un solo bucle.
;
; Convencion de registros: la de `starfield.asm`, mas
;   R28 temporal, tambien la direccion vieja al rotar
; ============================================================

.include "mmio.inc"

start:
    LI    R2, MMIO_VIDEO_BASE

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

    MOVI  R18, 128             ; Z_MIN
    MOVI  R19, 1151            ; Z_MAX
    MOVI  R20, 256             ; estrellas
    MOVI  R21, 6               ; paso de acercamiento
    MOVI  R22, 320
    MOVI  R23, 240
    MOVI  R24, 640
    MOVI  R25, 1

    ; ---- borrar los dos buffers, una sola vez ----
    ; Son contiguos, asi que un bucle cubre los 307 200 bytes. A partir de
    ; aqui ya nadie vuelve a borrar una pantalla entera.
    MOVHI R26, 0x0100
    MOVHI R27, 0x0104
    ORI   R27, R27, 0xB000     ; 0x01000000 + 2*153600
clear_both:
    STORE R0, R26, 0
    ADDI  R26, R26, 4
    BLTU  R26, R27, clear_both

    ; ---- sembrar el campo ----
    ; Mismo orden de tiradas que `starfield.asm` --z, x, y-- porque el campo
    ; tiene que salir identico. Las dos direcciones arrancan a cero: todavia
    ; no se ha pintado nada en ningun buffer.
    MOVHI R3, 0x0010           ; tabla de estrellas en 0x00100000
    MOVI  R12, 0
seed_loop:
    JAL   R31, rnd
    ANDI  R28, R17, 1023
    ADD   R28, R28, R18        ; z = Z_MIN + (0..1023)
    JAL   R29, spawn
    STORE R0, R3, 12           ; a0
    STORE R0, R3, 16           ; a1
    ADDI  R3, R3, 20
    ADDI  R12, R12, 1
    BLT   R12, R20, seed_loop

frame:
    LOAD  R1, R2, MMIO_VIDEO_FB_BACK_OFF            ; R1 = FB_BACK; cambia en cada intercambio

    ; ---- pasada 1: borrar lo de hace dos frames ----
    ; Las direcciones guardadas son absolutas --putpixel ya les sumo la base
    ; del buffer de entonces-- asi que a1 apunta dentro de este mismo buffer
    ; sin tener que recalcular nada.
    MOVHI R3, 0x0010
    MOVI  R12, 0
erase_loop:
    LOAD  R28, R3, 16
    BEQ   R28, R0, no_erase    ; el centinela: ese frame no se pinto
    STOREH R0, R28, 0
no_erase:
    ADDI  R3, R3, 20
    ADDI  R12, R12, 1
    BLT   R12, R20, erase_loop

    ; ---- pasada 2: acercar y dibujar ----
    MOVHI R3, 0x0010
    MOVI  R12, 0
star_loop:
    ; Rotar las dos direcciones antes de nada. a0 pasa a a1, y a0 se pone al
    ; centinela; si al final se pinta algo, se sobreescribe con la direccion
    ; buena. Asi el camino de "no se pinto" no necesita rama propia.
    LOAD  R28, R3, 12
    STORE R28, R3, 16          ; a1 <- a0
    STORE R0,  R3, 12          ; a0 <- centinela

    LOAD  R9,  R3, 0           ; x
    LOAD  R10, R3, 4           ; y
    LOAD  R11, R3, 8           ; z

    SUB   R11, R11, R21        ; acercarse un paso
    BGE   R11, R18, alive

    ADDI  R28, R19, 0          ; z = Z_MAX, nunca aleatoria
    JAL   R29, spawn
    BRA   next_star

alive:
    STORE R11, R3, 8

    ; ---- proyeccion en perspectiva ----
    DIV   R4, R9, R11
    ADDI  R4, R4, 160
    DIV   R5, R10, R11
    ADDI  R5, R5, 120

    ; ---- recorte ----
    BLT   R4, R0,  next_star
    BGE   R4, R22, next_star
    BLT   R5, R0,  next_star
    BGE   R5, R23, next_star

    ; ---- brillo segun la distancia ----
    MOVI  R28, 400
    BLT   R11, R28, near
    MOVI  R28, 800
    BLT   R11, R28, mid
    ORI   R6, R0, 0x4208       ; lejos: gris oscuro
    BRA   plot
mid:
    ORI   R6, R0, 0x9492       ; medio: gris
    BRA   plot
near:
    ORI   R6, R0, 0xFFFF       ; cerca: blanco
plot:
    JAL   R30, putpixel
    STORE R7, R3, 12           ; a0 <- lo que acaba de pintar putpixel

next_star:
    ADDI  R3, R3, 20
    ADDI  R12, R12, 1
    BLT   R12, R20, star_loop

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R25, R2, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R28, R2, MMIO_VIDEO_SWAP_OFF
    BNE   R28, R0, wait_swap

    BRA   frame

; ------------------------------------------------------------
; rnd: siguiente valor del xorshift32. Estado en R13, salida tambien en R17.
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
; `SARI 16` se queda con la mitad ALTA y le extiende el signo de paso, que da
; [-32768, 32767] sin restar nada. No confundir con `SHLI 16` + `SARI 16`: eso
; es la mitad baja, la de peor calidad en xorshift32.
;
; No toca a0 ni a1: la rotacion ya los dejo como tocaba.
;
; Entrada: R3, R28. Usa R17 y R31. Vuelve por R29.
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
; Deja la direccion en R7, que aqui no es un efecto colateral sino parte del
; contrato: el bucle la guarda para borrarla dentro de dos frames.
;
; Entrada: R4, R5, R6. Salida: R7. Usa R8. Vuelve por R30.
; ------------------------------------------------------------
putpixel:
    MUL    R7, R5, R24         ; y * 640
    ADD    R8, R4, R4          ; x * 2
    ADD    R7, R7, R8
    ADD    R7, R7, R1
    STOREH R6, R7, 0
    JR     R30
