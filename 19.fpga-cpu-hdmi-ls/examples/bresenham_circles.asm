; ============================================================
; bresenham_circles.asm - circunferencias por el algoritmo del punto medio
;
; Seis circunferencias concentricas en el centro de la pantalla, con los radios
; creciendo un pixel por frame: se ve una onda que sale del centro y se repite.
;
; El algoritmo del punto medio --el Bresenham de circunferencias-- calcula solo
; el primer octante, de (r,0) a la diagonal, y saca los otros siete por
; simetria. Eso son 45 grados de trabajo para 360 de dibujo. El bucle no tiene
; ni raices ni senos: lleva un termino de error que dice si el punto medio
; entre los dos candidatos cae dentro o fuera de la circunferencia ideal, y esa
; comparacion es lo unico que decide si x baja o se queda.
;
; ---- Tres niveles de llamada, y donde esta el limite ----
;
; Aqui la cadena es main -> circle -> plot8 -> putpixel, un nivel mas que
; bresenham_lines.asm. Como el enlace vive en un registro, hacen falta TRES
; registros de enlace distintos: R31 para circle, R29 para plot8 y R30 para
; putpixel.
;
; Es el punto donde se ve que la tecnica se acaba. Con dos niveles repartir
; registros es mas barato que tocar memoria; con tres ya empieza a comerse el
; banco, y con recursion no vale de ninguna manera. Lo que toca a partir de
; aqui es una pila: salvar el enlace en memoria al entrar en cada rutina y
; restaurarlo al salir. Esta ISA no tiene push ni pop, pero tampoco le hacen
; falta: `STORE R31, Rsp, 0` y `LOAD R31, Rsp, 0` son eso mismo. El caso
; `calls-link-and-return` de x.cpu-tests lo hace asi. Ver docs/llamadas.md.
;
; plot8 esta escrito para reaprovechar lo ya calculado: cada llamada a putpixel
; cambia solo la coordenada que hace falta, asi que los ocho puntos salen con
; ocho sumas o restas en vez de dieciseis.
;
; ---- Detalles de esta maquina ----
;
; R0 ES UN REGISTRO GENERAL, no un cero cableado, asi que R3 guarda el cero con
; el que se compara. Es la razon de que JR tenga opcode propio en vez de ser
; `JALR R0, Ra, 0`.
;
; Los radios llegan como mucho a 111 y el centro es (160,120), asi que los
; ocho puntos simetricos caen siempre dentro de la pantalla: x entre 49 y 271,
; y entre 9 y 231. Por eso putpixel no comprueba limites. Si se tocan los
; radios hay que rehacer esa cuenta, o el dibujo se escribira encima del otro
; buffer.
;
; RGB565:  bits 15:11 rojo   bits 10:5 verde   bits 4:0 azul
;
; Registros de video, en 0x80000000:
;   +0  FB_FRONT   +4  FB_BACK   +8  SWAP   +12  STATUS
;
; Convencion de registros:
;   R1  base del buffer trasero         R2  base de los registros de video
;   R3  constante 0
;   R4  x de putpixel    R5  y de putpixel    R6  color
;   R7, R8  temporales de putpixel
;   R9  centro x    R10 centro y
;   R11 x del octante   R12 y del octante   R13 error   R14 radio
;   R17 temporal de circle y del color
;   R20 numero de circunferencia   R21 radio actual   R22 radio base animado
;   R23 constante 1   R24 constante 640   R25 constante 11 (sitio del rojo)
;   R26 puntero de borrado   R27 fin de borrado   R28 temporal
;   R29 enlace de plot8   R30 enlace de putpixel   R31 enlace de circle
; ============================================================
.include "mmio.inc"

start:
    LI    R2, MMIO_VIDEO_BASE

    ; Elegir donde vive el framebuffer. Tras el reset las dos bases valen
    ; cero --el framebuffer es una decision del programa, no una reserva
    ; que el hardware impone-- asi que heredarlas seria dibujar sobre el
    ; propio programa. La direccion es la de siempre; lo que cambia es que
    ; ahora hay que escribirla.
    MOVHI R30, 0x0100
    STORE R30, R2, MMIO_VIDEO_FB_FRONT_OFF          ; FB_FRONT
    MOVHI R30, 0x0102
    ORI   R30, R30, 0x5800
    STORE R30, R2, MMIO_VIDEO_FB_BACK_OFF          ; FB_BACK, un frame mas arriba

    ; Encender el scanout. Tras el reset el modo es PATTERN --la memoria
    ; recien encendida contiene basura, asi que arrancar leyendola daria
    ; una salida indefinida-- y un programa que dibuja tiene que pedir
    ; que se vea lo que dibuja. Ver video_registers.v, VIDEO_CTRL.
    MOVI  R30, 2               ; SCANOUT
    STORE R30, R2, MMIO_VIDEO_CTRL_OFF         ; VIDEO_CTRL
    MOVI  R3, 0                ; el cero con el que se compara; R0 no lo es
    MOVI  R23, 1
    MOVI  R24, 640
    MOVI  R25, 11
    MOVI  R22, 4               ; radio base de partida

frame:
    LOAD  R1, R2, MMIO_VIDEO_FB_BACK_OFF            ; R1 = FB_BACK; cambia en cada intercambio

    ; ---- borrar el buffer trasero ----
    ADDI  R26, R1, 0
    MOVHI R27, 0x0002
    ORI   R27, R27, 0x5800     ; 320*240*2 = 153600 bytes
    ADD   R27, R27, R1
clear:
    STORE R3, R26, 0           ; fondo negro
    ADDI  R26, R26, 4
    BLTU  R26, R27, clear

    ; ---- las seis circunferencias ----
    MOVI  R20, 0
    ADDI  R21, R22, 0

next_circle:
    ; Color: el rojo decrece y el azul crece con el numero de circunferencia,
    ; asi que la de fuera es azul y la de dentro roja.
    MOVI  R17, 5
    MUL   R17, R20, R17        ; 5n
    MOVI  R6, 31
    SUB   R6, R6, R17          ; rojo5 = 31 - 5n
    SHL   R6, R6, R25
    ADDI  R17, R17, 1          ; azul5 = 5n + 1
    OR    R6, R6, R17

    MOVI  R9, 160              ; centro de la pantalla
    MOVI  R10, 120
    ADDI  R14, R21, 0
    JAL   R31, circle

    ADDI  R21, R21, 18         ; separacion entre circunferencias
    ADDI  R20, R20, 1
    MOVI  R28, 6
    BLT   R20, R28, next_circle

    ; ---- pedir el intercambio y esperar a que el hardware lo aplique ----
    STORE R23, R2, MMIO_VIDEO_SWAP_OFF           ; SWAP = 1
wait_swap:
    LOAD  R28, R2, MMIO_VIDEO_SWAP_OFF
    BNE   R28, R3, wait_swap

    ; Crecer un pixel por frame y volver a empezar. El ciclo son 18 frames,
    ; que es la separacion entre circunferencias: al reiniciarse, cada una cae
    ; donde estaba la de dentro, y la onda parece continua.
    ADDI  R22, R22, 1
    MOVI  R28, 22
    BLT   R22, R28, frame
    MOVI  R22, 4
    BRA   frame

; ------------------------------------------------------------
; circle: dibuja la circunferencia de radio R14 centrada en (R9,R10), color R6.
;
; Algoritmo del punto medio. Se recorre el octante que va de (r,0) hacia la
; diagonal: y sube de uno en uno siempre, y x baja solo cuando el error dice
; que el pixel se ha alejado demasiado. La condicion de parada es x >= y, o sea
; llegar a la diagonal; a partir de ahi el resto es simetria.
;
; Entrada: R9, R10, R14 y R6.
; Destruye R11, R12, R13 y R17, ademas de lo de plot8. Vuelve por R31.
; ------------------------------------------------------------
circle:
    ADDI  R11, R14, 0          ; x = r
    MOVI  R12, 0               ; y = 0
    MOVI  R13, 0               ; error acumulado

circle_step:
    BLT   R11, R12, circle_done   ; mientras x >= y
    JAL   R29, plot8

    ADDI  R12, R12, 1          ; y siempre sube
    ADD   R17, R12, R12
    ADDI  R17, R17, 1          ; 2y + 1
    ADD   R13, R13, R17        ; err += 2y + 1

    ; x baja si 2*(err - x) + 1 > 0, o sea si el punto medio se ha salido.
    SUB   R17, R13, R11
    ADD   R17, R17, R17
    ADDI  R17, R17, 1
    BGE   R3, R17, circle_step ; si no es positivo, x se queda donde esta

    ADDI  R11, R11, -1
    ADD   R17, R11, R11
    SUB   R17, R3, R17
    ADDI  R17, R17, 1          ; 1 - 2x
    ADD   R13, R13, R17        ; err += 1 - 2x
    BRA   circle_step

circle_done:
    RET                        ; alias de JR R31

; ------------------------------------------------------------
; plot8: pinta los ocho puntos simetricos de (R11,R12) alrededor de (R9,R10).
;
; El orden no es caprichoso: cada llamada cambia UNA sola coordenada respecto a
; la anterior, asi que los ocho puntos cuestan ocho sumas en vez de dieciseis.
; Se apoya en que putpixel no toca R4 ni R5.
;
; Entrada: R9, R10, R11, R12 y R6. Vuelve por R29.
; ------------------------------------------------------------
plot8:
    ADD   R4, R9, R11
    ADD   R5, R10, R12
    JAL   R30, putpixel        ; ( x,  y)
    SUB   R4, R9, R11
    JAL   R30, putpixel        ; (-x,  y)
    SUB   R5, R10, R12
    JAL   R30, putpixel        ; (-x, -y)
    ADD   R4, R9, R11
    JAL   R30, putpixel        ; ( x, -y)

    ADD   R4, R9, R12          ; y ahora con las coordenadas cambiadas
    ADD   R5, R10, R11
    JAL   R30, putpixel        ; ( y,  x)
    SUB   R4, R9, R12
    JAL   R30, putpixel        ; (-y,  x)
    SUB   R5, R10, R11
    JAL   R30, putpixel        ; (-y, -x)
    ADD   R4, R9, R12
    JAL   R30, putpixel        ; ( y, -x)
    JR    R29

; ------------------------------------------------------------
; putpixel: escribe el pixel (R4, R5) del color R6 en el buffer trasero.
;
; direccion = base + y*640 + x*2. El y*640 va con MUL, que son 11 ciclos frente
; a los 37 de los dos SHL iterativos que usan las demos heredadas de la 18.
;
; Entrada: R4, R5, R6. No los modifica. Usa R7 y R8. Vuelve por R30.
; ------------------------------------------------------------
putpixel:
    MUL    R7, R5, R24         ; y * 640
    ADD    R8, R4, R4          ; x * 2
    ADD    R7, R7, R8
    ADD    R7, R7, R1
    STOREH R6, R7, 0           ; un pixel, dos bytes, sin leer nada antes
    JR     R30
