; Efecto a pantalla completa con los 64 hilos colaborando.
;
; Con DOBLE BUFFER: dibuja en FB_BACK y pide el intercambio al terminar cada
; frame. Sin el, el scanout lee a 60 Hz la misma memoria que estos hilos
; reescriben a ~8 fps y la imagen tiembla, porque cada frame mostrado mezcla
; contenido viejo y nuevo.
;
; El host prepara los dos buffers y enciende el scanout antes de arrancar:
;     FB_FRONT (0x80000204) = 0x00100000
;     FB_BACK  (0x80000208) = 0x00140000
;     VIDEO_CTRL (0x80000200) = 2
;
; El intercambio SI lo pide la GPU, escribiendo SWAP (0x8000020c). Eso solo es
; posible desde que la ventana MMIO esta abierta a la LSU (ver mmio.md): antes
; la LSU marcaba fault todo lo que pasara de 0x02000000 y ademas el MMIO exigia
; `halted`. El host no podria hacerlo, tendria que pedir un intercambio ocho
; veces por segundo por UART.
;
; Reparto del trabajo
; -------------------
; GETTID devuelve el id GLOBAL 0..63 ({warp,lane}), asi que los 64 hilos se
; reparten el framebuffer sin coordinarse.
;
; 320x240 RGB565 = 38 400 palabras de 32 bits (2 pixeles por palabra), o sea
; 600 palabras por hilo. El hilo t coge las palabras t, t+64, t+128...
;
; El paso de 64 es a proposito: los 8 hilos de un warp escriben palabras
; CONSECUTIVAS, o sea 32 bytes seguidos, que la LSU v2 coalesce en 2
; transacciones de 16 bytes en vez de 8 accesos sueltos.
;
; x2 (columna de palabra) e y se llevan al dia sumando, sin dividir: como
; 64 < 160, cada paso cruza como mucho un final de fila.
;
; El efecto
; ---------
; La primera version usaba (x+t)&31 y (y+t)&63 directos. En pantalla salian
; CUATRO bandas horizontales con un corte seco (240 filas / 64 = 3,75 vueltas)
; y rayas verticales cada 32 pixeles. Funcionaba, pero parecia ruido: el
; problema es que un diente de sierra en un canal de color es una costura muy
; visible.
;
; Esta version evita dar la vuelta:
;   r = (x2 >> 4) + tex     degradado horizontal suave, 0..9, sin vuelta
;   g = y >> 2              degradado vertical suave, 0..59 en 240 filas
;   b = tex * 2             textura, 0..30
;   tex = ((x + t) ^ y) & 15   moire XOR de amplitud baja, que se desplaza con t
;
; Asi el fondo es un degradado limpio y el XOR queda como detalle encima,
; moviendose. Ningun canal corta en seco.
;
; Y el coste: los SHL son de UN BIT POR CICLO en esta ISA (STATE_SHIFT_STEP),
; asi que la version anterior gastaba 48 ciclos por palabra solo desplazando
; (11+5+11+5+16). Aqui los desplazamientos grandes se hacen con MUL por una
; constante, que son 4 estados fijos, y los pocos SHR que quedan son de 2 y 4.

        GETTID R1               ; R1 = id global 0..63
        MOVHI R30, 0x8000       ; R30 = 0x80000000, base del MMIO
        MOVI  R21, 160          ; palabras por fila
        MOVI  R22, 2048         ; rojo  -> bits 15:11, con MUL en vez de SHL 11
        MOVI  R23, 32           ; verde -> bits 10:5
        MOVHI R24, 0x0001       ; 65536: pixel derecho a la mitad alta
        MOVI  R25, 4            ; x2 >> 4
        MOVI  R26, 2            ; y  >> 2
        MOVI  R28, 4            ; frames a dibujar (subir para dejarlo animando)
        MOVI  R2, 0             ; R2 = t, contador de frames

frame_loop:
        LOAD  R19, R30, 520     ; R19 = FB_BACK (0x80000208): donde toca dibujar
        ADD   R3, R1, R0        ; x2 = tid
        MOVI  R4, 0             ; y  = 0
        ADD   R5, R1, R0        ; w  = tid
        MOVI  R6, 600           ; palabras por hilo
        SHR   R16, R4, R26      ; gy = y >> 2
        MUL   R18, R16, R23     ; gy ya colocado en bits 10:5

pix_loop:
        ADD   R7, R3, R3        ; x = x2 * 2 (pixel izquierdo)
        SHR   R17, R3, R25      ; rx = x2 >> 4, comun a los dos pixeles

        ADD   R8, R7, R2        ; --- pixel izquierdo ---
        XOR   R8, R8, R4
        ANDI  R8, R8, 15        ; tex
        ADD   R9, R17, R8       ; r = rx + tex
        ADD   R10, R8, R8       ; b = tex * 2
        MUL   R9, R9, R22       ; r a bits 15:11
        ADD   R9, R9, R18       ; + verde
        ADD   R11, R9, R10      ; + azul  -> pixel izquierdo

        ADDI  R12, R7, 1        ; --- pixel derecho ---
        ADD   R8, R12, R2
        XOR   R8, R8, R4
        ANDI  R8, R8, 15
        ADD   R9, R17, R8
        ADD   R10, R8, R8
        MUL   R9, R9, R22
        ADD   R9, R9, R18
        ADD   R13, R9, R10      ; pixel derecho
        MUL   R13, R13, R24     ; a la mitad alta
        ADD   R11, R11, R13     ; los dos pixeles en una palabra

        ADD   R14, R5, R5       ; direccion = base + w*4
        ADD   R14, R14, R14
        ADD   R14, R19, R14
        STORE R11, R14, 0

        ADDI  R5, R5, 64        ; siguiente palabra de este hilo
        ADDI  R3, R3, 64
        BLT   R3, R21, no_wrap
        SUB   R3, R3, R21       ; cruzo el final de la fila
        ADDI  R4, R4, 1
        SHR   R16, R4, R26      ; gy solo se recalcula al cambiar de fila
        MUL   R18, R16, R23
no_wrap:
        ADDI  R6, R6, -1
        BNE   R6, R0, pix_loop

        BAR                     ; frame dibujado: todos los hilos han terminado

        ; Pedir el intercambio y esperar a que ocurra. Lo hace UN solo hilo:
        ; un salto divergente necesita SSY delante o el SM para con ERROR_SIMT.
        SSY   swapped
        BNE   R1, R0, swapped
        MOVI  R15, 1
        STORE R15, R30, 524     ; SWAP = 1 (0x8000020c)
poll_swap:
        LOAD  R15, R30, 524
        ANDI  R15, R15, 1
        BNE   R15, R0, poll_swap
swapped:
        BAR                     ; ya se puede dibujar en el nuevo trasero

        ADDI  R2, R2, 1         ; siguiente frame
        BAR
        ADDI  R28, R28, -1
        BNE   R28, R0, frame_loop

        BAR
        HALT
