; Variante de plasma SIN accesos a MMIO, para validar 23.gpu-sim-uarch.
;
; El simulador funcional de 11.gpu-sim-func no tiene ventana MMIO -- y no debe
; tenerla, no es su trabajo. Asi que un programa con LOAD/STORE a 0x80000xxx
; revienta ahi con ERROR_MEMORY_ACCESS y el modelo de ciclos acaba midiendo un
; recorrido distinto al del RTL.
;
; Esta version usa una base de framebuffer fija y no pide intercambio, asi que
; RTL y modelo ejecutan EXACTAMENTE la misma secuencia. Es la referencia de
; calibracion, no un programa util.
;
; ES LA EXCEPCION A LA REGLA. Los demas ejemplos de esta carpeta se configuran
; el video ellos mismos, para que `run-board --program` baste. Este NO PUEDE:
; en el momento en que escriba un registro MMIO deja de correr en el simulador
; funcional y se acaba su unica razon de existir. Si quieres verlo en pantalla,
; enciende el scanout a mano desde el monitor:
;     python monitor.py write-byte 0x80000002 0x10   ; FB_FRONT = 0x00100000
;     python monitor.py write-byte 0x80000018 2      ; VIDEO_CTRL = SCANOUT
;
; Ademas hay un numero de oro colgando de este fichero: test_programs.py de
; 25.gpu-sim-cycle-uarch comprueba que un frame retire 151 880 instrucciones.
; Cualquier instruccion que le anadas lo rompe.
; Efecto a pantalla completa con los 64 hilos colaborando.
;
; SIN DOBLE BUFFER, a proposito. Dibuja siempre sobre la base fija 0x00100000
; (el MOVHI R19 del frame_loop) y NUNCA escribe SWAP, asi que el frente se queda
; donde lo dejo el host. La imagen tiembla -- es el precio de no tocar MMIO, y
; aqui no importa porque esto no se mira en pantalla, se compara contra el
; modelo palabra por palabra.
;
; Quien ejercita el doble buffer y el intercambio es plasma.asm. Si buscas como
; se pide un SWAP desde la GPU, mira alli, no aqui.
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
        NOP
        MOVI  R21, 160          ; palabras por fila
        MOVI  R22, 2048         ; rojo  -> bits 15:11, con MUL en vez de SHL 11
        MOVI  R23, 32           ; verde -> bits 10:5
        MOVHI R24, 0x0001       ; 65536: pixel derecho a la mitad alta
        MOVI  R25, 4            ; x2 >> 4
        MOVI  R26, 2            ; y  >> 2
        MOVI  R28, 1            ; UN frame: version para perfilar
        MOVI  R2, 0             ; R2 = t, contador de frames

frame_loop:
        MOVHI R19, 0x0010       ; base fija: sin MMIO, para validar el modelo
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

        BAR                     ; ya se puede dibujar en el nuevo trasero

        ADDI  R2, R2, 1         ; siguiente frame
        BAR
        ADDI  R28, R28, -1
        BNE   R28, R0, frame_loop

        BAR
        HALT
