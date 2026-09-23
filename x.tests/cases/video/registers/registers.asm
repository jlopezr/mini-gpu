; ============================================================
; registers.asm - la ventana de registros de video, desde un programa
;
; No dibuja nada. Comprueba lo unico que un programa necesita saber de los
; registros para usar el doble buffer:
;
;   - una base escrita se relee EXACTA: el programa pone FB_FRONT y FB_BACK al
;     arrancar y comprueba que valen lo que escribio. OJO: esto NO comprueba el
;     valor de encendido, que no es asunto de un programa. Antes las heredaba
;     del runner, y como solo el reset de la placa reinicia esas bases, un caso
;     anterior que dejara un numero impar de intercambios se las pasaba
;     cruzadas y este fallaba una de cada dos veces;
;   - escribir FB_BACK lo cambia, y se alinea a cuatro bytes;
;   - escribir SWAP pide un intercambio, y al aplicarse las dos bases se
;     INTERCAMBIAN, no se copia una sobre la otra;
;   - STATUS deja leer el underflow.
;
; Por que no se comprueba que SWAP quede pendiente justo despues de pedirlo:
; entre la escritura y la lectura pasan unos microsegundos, y el intercambio
; ocurre en el arranque de frame, cada 16,7 ms. La probabilidad de que caiga
; justo en medio es diminuta pero no cero, y un caso que falla una vez de cada
; mil es peor que no tenerlo. Lo que se hace es ESPERAR a que se aplique, que
; ademas es lo que hace un programa de verdad.
;
; Solo usa los cuatro registros que existen desde la 16, asi que este caso
; corre tambien alli: es el que justifica que `video` y `frame_capture` sean
; capacidades distintas.
;
; Registros:
;   R20 base de los registros     R21 constante 1
;   R1  FB_FRONT antes            R2  FB_BACK antes
;   R3  FB_FRONT despues          R4  FB_BACK despues
;   R5  FB_BACK tras escribirlo   R6  underflow
;   R8  temporal de espera         R0  cero, cableado por la ISA
; ============================================================

.include "mmio.inc"

start:
    LI    R20, MMIO_VIDEO_BASE
    ; El cero sale de R0, que la ISA cablea. Hasta el backport aqui habia un
    ; `MOVI R9, 0`: mientras R0 fue un registro general en cinco de los seis
    ; backends, usarlo habria funcionado por casualidad --los registros
    ; arrancan a cero-- hasta el dia que alguien lo escribiera.

    ; ---- partida conocida ----
    ; Las pone ESTE programa, no el runner. Antes las heredaba, y eso obligaba
    ; al arnes a normalizarlas antes de cada ejecucion: solo el reset de la
    ; placa reinicia las bases, asi que un caso anterior que dejara un numero
    ; impar de intercambios se las pasaba cruzadas y este fallaba una de cada
    ; dos veces. Poniendolas aqui, el caso no depende de nadie y comprueba
    ; ademas que una base escrita se lee EXACTA.
    MOVHI R9, 0x0100
    STORE R9, R20, MMIO_VIDEO_FB_FRONT_OFF
    MOVHI R9, 0x0102
    ORI   R9, R9, 0x5800
    STORE R9, R20, MMIO_VIDEO_FB_BACK_OFF

    ; ---- valores iniciales ----
    LOAD  R1, R20, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT
    LOAD  R2, R20, MMIO_VIDEO_FB_BACK_OFF            ; FB_BACK

    ; ---- escribir FB_BACK y releerlo ----
    ; Se escribe una base alineada a 16 bytes y tiene que salir EXACTA. Hasta
    ; MMIO v2 aqui se escribian los dos bits bajos a uno para ver que el
    ; hardware los ignoraba; §9.2 convirtio eso en un error de acceso, y un
    ; programa no puede comprobar su propio fallo: lo hace `video-fb-desalineada`.
    MOVHI R7, 0x0110
    STORE R7, R20, MMIO_VIDEO_FB_BACK_OFF
    LOAD  R5, R20, MMIO_VIDEO_FB_BACK_OFF            ; debe salir 0x01100000

    ; ---- devolver FB_BACK a su sitio y pedir intercambio ----
    STORE R2, R20, MMIO_VIDEO_FB_BACK_OFF
    MOVI  R21, 1
    STORE R21, R20, MMIO_VIDEO_SWAP_OFF          ; SWAP

wait_swap:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF
    BNE   R8, R0, wait_swap    ; esperar a que el hardware lo aplique

    ; ---- tras el intercambio, las bases estan cruzadas ----
    LOAD  R3, R20, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT, deberia valer el FB_BACK de antes
    LOAD  R4, R20, MMIO_VIDEO_FB_BACK_OFF            ; FB_BACK,  deberia valer el FB_FRONT de antes

    ; ---- underflow ----
    LOAD  R6, R20, MMIO_VIDEO_STATUS_OFF
    ANDI  R6, R6, 1

    HALT
