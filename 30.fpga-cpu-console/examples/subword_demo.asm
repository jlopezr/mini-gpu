; ============================================================
; subword_demo.asm - degradado RGB565 pixel a pixel con STOREH
;
; Es el caso de uso que motiva las instrucciones de 16 bits. El framebuffer es
; RGB565: 320x240 pixeles de dos bytes, 640 bytes por linea. Con solo STORE de
; 32 bits, escribir UN pixel obliga a leer la palabra que lo contiene, mezclar
; la mitad que toca y volver a escribirla: tres instrucciones y una lectura de
; memoria por pixel. Por eso los demos de la 18 (swap_demo, tear_demo) pintan
; bandas de color plano: repiten el mismo color en las dos mitades de la
; palabra y asi se ahorran el problema, pero a cambio no pueden pintar dos
; pixeles vecinos distintos sin pagarlo.
;
; Con STOREH cada pixel es una instruccion y no hay lectura ninguna, asi que un
; degradado horizontal sale igual de barato que una banda plana. Eso es lo que
; dibuja este programa: rojo creciente con x, verde creciente con y.
;
; No se busca velocidad. Los desplazamientos de esta CPU son iterativos --un
; bit por ciclo, ver cpu.v-- asi que los tres SHL/SHR por pixel dominan el
; coste y el frame tarda bastante mas que el de swap_demo_fast. Lo que se
; enseña aqui es la escritura parcial, no el rendimiento.
;
; RGB565:  bits 15:11 rojo   bits 10:5 verde   bits 4:0 azul
;
; Registros de video, en 0x80000000:
;   +0  FB_FRONT   +4  FB_BACK   +8  SWAP   +12  STATUS
;
; Convencion de registros:
;   R1  base del buffer trasero    R2  y (linea)
;   R3  x (pixel)                  R4  direccion de la linea
;   R5  temporal                   R6  puntero de escritura
;   R7  constante 1                R8  lectura de SWAP
;   R9  constante 0                R14 constante 9   R15 constante 7
;   R16 verde de esta linea, ya colocado en su sitio
;   R17 color del pixel            R20 base de los registros
;   R22 alto                       R23 ancho
;   R24 constante 4   R25 constante 11   R26 constante 2   R27 constante 5
; ============================================================

.include "mmio.inc"

start:
    LI    R20, MMIO_VIDEO_BASE

    ; Elegir donde vive el framebuffer. Tras el reset las dos bases valen
    ; cero --el framebuffer es una decision del programa, no una reserva
    ; que el hardware impone-- asi que heredarlas seria dibujar sobre el
    ; propio programa. La direccion es la de siempre; lo que cambia es que
    ; ahora hay que escribirla.
    MOVHI R30, 0x0100
    STORE R30, R20, MMIO_VIDEO_FB_FRONT_OFF          ; FB_FRONT
    MOVHI R30, 0x0102
    ORI   R30, R30, 0x5800
    STORE R30, R20, MMIO_VIDEO_FB_BACK_OFF          ; FB_BACK, un frame mas arriba

    ; Encender el scanout. Tras el reset el modo es PATTERN --la memoria
    ; recien encendida contiene basura, asi que arrancar leyendola daria
    ; una salida indefinida-- y un programa que dibuja tiene que pedir
    ; que se vea lo que dibuja. Ver video_registers.v, VIDEO_CTRL.
    MOVI  R30, 2               ; SCANOUT
    STORE R30, R20, MMIO_VIDEO_CTRL_OFF         ; VIDEO_CTRL
    MOVI  R7, 1
    MOVI  R9, 0
    MOVI  R14, 9               ; desplazamientos para *640
    MOVI  R15, 7
    MOVI  R22, 240             ; alto
    MOVI  R23, 320             ; ancho
    MOVI  R24, 4               ; x>>4  da 0..19, que cabe en los 5 bits de rojo
    MOVI  R25, 11              ; rojo empieza en el bit 11
    MOVI  R26, 2               ; y>>2  da 0..59, que cabe en los 6 de verde
    MOVI  R27, 5               ; verde empieza en el bit 5

frame:
    LOAD  R1, R20, MMIO_VIDEO_FB_BACK_OFF           ; R1 = FB_BACK; cambia en cada intercambio
    MOVI  R2, 0

line:
    SHL   R4, R2, R14          ; y*512
    SHL   R5, R2, R15          ; y*128
    ADD   R4, R4, R5           ; y*640
    ADD   R4, R4, R1           ; + base del buffer

    SHR   R16, R2, R26         ; el verde solo depende de la linea: fuera del
    SHL   R16, R16, R27        ; bucle de pixeles

    MOVI  R3, 0
    ADDI  R6, R4, 0

pixel:
    SHR   R17, R3, R24
    SHL   R17, R17, R25        ; rojo en su sitio
    OR    R17, R17, R16        ; mas el verde de la linea
    STOREH R17, R6, 0          ; UN pixel, dos bytes, sin leer nada antes
    ADDI  R6, R6, 2
    ADDI  R3, R3, 1
    BLT   R3, R23, pixel

    ADDI  R2, R2, 1
    BLT   R2, R22, line

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R7, R20, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF
    BNE   R8, R9, wait_swap

    BRA   frame
