; ============================================================
; double-buffer.asm - el contrato de doble buffer, igual en CPU y en GPU
;
; Este es EL MISMO BINARIO en las dos familias. Es la prueba de que el mapa
; MMIO unificado es un contrato y no dos parecidos: si la 21 y la 22 no
; respondieran igual a las mismas escrituras, este caso fallaria en una de las
; dos.
;
; Tres cosas lo hacen portable, y las tres son deliberadas:
;
;   - UN SOLO HILO. Un programa de GPU normal reparte trabajo con GETTID entre
;     64 hilos, y eso no existe en la CPU. Aqui el reparto se evita desde
;     fuera: `warps.json` deja `active_mask: 1`, un unico hilo activo, asi que
;     no hace falta ninguna guarda dentro del programa y el codigo puede ser
;     literalmente el mismo.
;
;   - NO DEPENDE DE LAS BASES DE ENCENDIDO. FB_FRONT y FB_BACK arrancan con
;     valores distintos en cada familia -y la fase 3.5 planea cambiarlos-, asi
;     que el caso no afirma NINGUNA direccion absoluta: lee lo que haya y
;     comprueba relaciones entre esos valores. Por eso el valor "sucio" que se
;     escribe se construye sobre FB_BACK en vez de ser una constante: se queda
;     dentro de un buffer valido en las dos familias.
;
;   - EL RESULTADO VA A MEMORIA, no a registros. Un caso de CPU declara
;     `expect.registers` y uno de GPU los mete dentro de `expect.warps`: son
;     formas distintas y un caso no puede usar las dos. `memory_dumps` es
;     identico en ambas.
;
; La palabra de resultado lleva la marca 0x5A5A en la parte alta y un bit por
; comprobacion en la baja. La marca no es decorativa: si fuese un mapa de bits
; a secas, "todo cero" significaria a la vez "fallaron las cuatro" y "el
; programa no llego a ejecutarse", y la memoria ya arranca a cero. Con la marca,
; un programa que no corre deja 0x00000000 y el caso falla, que es lo correcto.
;
; Solo usa instrucciones base: ni MUL, ni SLT, ni accesos de subpalabra. Tiene
; que correr en la 12 y en la 10 igual que en la 22.
;
; Registros:
;   R20 base de los registros de video   R19 destino del resultado
;   R10 palabra de resultado             R1  FB_FRONT antes
;   R2  FB_BACK antes                    R3  FB_FRONT despues
;   R4  FB_BACK despues                  R5  FB_BACK releido
;   R6  underflow                        R11 valor sucio
;   R12 comparacion                      R8  temporal de espera
;   R13 VIDEO_CTRL antes                 R14 modo de prueba (SCANOUT)
;   R15 VIDEO_CTRL releido
;   R0  cero, cableado por la ISA
; ============================================================

.include "mmio.inc"

    LI    R20, MMIO_VIDEO_BASE  ; base de los registros de video
    MOVI  R19, 0x0200          ; donde dejar el resultado
    MOVHI R10, 0x5A5A          ; marca; los bits de comprobacion van debajo

    LOAD  R1, R20, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT antes
    LOAD  R2, R20, MMIO_VIDEO_FB_BACK_OFF           ; FB_BACK antes

    ; ---- bit 0: escribir FB_BACK lo cambia, y se relee EXACTO ----
    ; Hasta MMIO v2 esto escribia FB_BACK con los dos bits bajos a uno y
    ; comprobaba que el hardware los ignoraba. Ya no: §9.2 dice que una base
    ; desalineada es ERROR, no se trunca, asi que ese programa ahora aborta y
    ; no hay forma de comprobarlo desde dentro --un programa no puede capturar
    ; su propio fallo de acceso; eso lo prueba `video-fb-desalineada`--.
    ; Lo que queda aqui es la mitad que si depende del doble buffer: el
    ; registro guarda lo que se le escribe, sin inventarse bits.
    ;
    ; El valor se construye sobre FB_BACK, no sobre una constante: asi sigue
    ; apuntando a un buffer valido en las dos familias --que no comparten
    ; mapa de memoria-- y el barrido no lee basura mientras tanto. El
    ; desplazamiento es de 16 bytes, el alineamiento que exige v2.
    ADDI  R11, R2, 16
    STORE R11, R20, MMIO_VIDEO_FB_BACK_OFF
    LOAD  R5, R20, MMIO_VIDEO_FB_BACK_OFF
    STORE R2, R20, MMIO_VIDEO_FB_BACK_OFF   ; se deja como estaba ANTES de
                                            ; comparar: si se restaurase
                                            ; despues, fallar el bit 0 se
                                            ; llevaria por delante los bits 1
                                            ; y 2 y un fallo pareceria tres
    XOR   R12, R5, R11         ; 0 si se guardo tal cual
    BNE   R12, R0, pedir_swap
    ORI   R10, R10, 0x0001

pedir_swap:
    ; ---- pedir el intercambio y ESPERAR a que se aplique ----
    ; No se comprueba que SWAP quede pendiente justo despues de escribirlo: el
    ; intercambio ocurre en el arranque de frame, cada 16,7 ms, y entre las dos
    ; instrucciones pasan microsegundos. Seria un caso que falla una vez de
    ; cada mil, que es peor que no tenerlo.
    MOVI  R21, 1
    STORE R21, R20, MMIO_VIDEO_SWAP_OFF
esperar:
    LOAD  R8, R20, MMIO_VIDEO_SWAP_OFF
    BNE   R8, R0, esperar

    LOAD  R3, R20, MMIO_VIDEO_FB_FRONT_OFF           ; FB_FRONT despues
    LOAD  R4, R20, MMIO_VIDEO_FB_BACK_OFF           ; FB_BACK despues

    ; ---- bit 1: las bases se INTERCAMBIAN, no se copia una sobre otra ----
    XOR   R12, R3, R2          ; el FB_FRONT nuevo es el FB_BACK viejo
    BNE   R12, R0, comprobar_back
    ORI   R10, R10, 0x0002

comprobar_back:
    ; ---- bit 2: y la otra mitad del intercambio ----
    XOR   R12, R4, R1          ; el FB_BACK nuevo es el FB_FRONT viejo
    BNE   R12, R0, comprobar_underflow
    ORI   R10, R10, 0x0004

comprobar_underflow:
    ; ---- bit 3: el barrido no se quedo sin datos ----
    LOAD  R6, R20, MMIO_VIDEO_STATUS_OFF
    ANDI  R6, R6, 1
    BNE   R6, R0, comprobar_ctrl
    ORI   R10, R10, 0x0008

comprobar_ctrl:
    ; ---- bit 4: VIDEO_CTRL acepta el modo que se le escribe ----
    ; Es la pieza que IGUALA los dos bloques: hasta la fase 3.5 solo existia en
    ; la GPU, y por eso esta en +0x18 y no en +0x00 --el hueco de HALT_AT, que
    ; solo tiene la CPU, hay que respetarlo en las dos--.
    ;
    ; El modo se restaura al valor que tenia. No es cortesia: solo el reset de
    ; la placa lo reinicia, asi que un caso que lo dejara cambiado se lo pasaria
    ; al siguiente, y el resultado dependeria del orden de ejecucion. Es el
    ; mismo error que ya se pago una vez con las bases de framebuffer.
    LOAD  R13, R20, MMIO_VIDEO_CTRL_OFF         ; modo actual
    MOVI  R14, 2               ; SCANOUT
    STORE R14, R20, MMIO_VIDEO_CTRL_OFF
    LOAD  R15, R20, MMIO_VIDEO_CTRL_OFF
    XOR   R12, R15, R14
    STORE R13, R20, MMIO_VIDEO_CTRL_OFF         ; dejarlo como estaba, pase lo que pase
    BNE   R12, R0, terminar
    ORI   R10, R10, 0x0010

terminar:
    STORE R10, R19, 0
    HALT
