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
;   R0  cero, cableado por la ISA
; ============================================================

    MOVHI R20, 0x8000          ; base de los registros de video
    MOVI  R19, 0x0200          ; donde dejar el resultado
    MOVHI R10, 0x5A5A          ; marca; los bits de comprobacion van debajo

    LOAD  R1, R20, 0           ; FB_FRONT antes
    LOAD  R2, R20, 4           ; FB_BACK antes

    ; ---- bit 0: escribir FB_BACK ignora los dos bits bajos ----
    ; El valor sucio se construye sobre FB_BACK, no sobre una constante: asi
    ; sigue apuntando a un buffer valido en las dos familias y el barrido no
    ; lee basura mientras tanto.
    ORI   R11, R2, 0x0003
    STORE R11, R20, 4
    LOAD  R5, R20, 4
    XOR   R12, R5, R2          ; 0 si el hardware alineo a cuatro
    BNE   R12, R0, pedir_swap
    ORI   R10, R10, 0x0001

pedir_swap:
    ; ---- pedir el intercambio y ESPERAR a que se aplique ----
    ; No se comprueba que SWAP quede pendiente justo despues de escribirlo: el
    ; intercambio ocurre en el arranque de frame, cada 16,7 ms, y entre las dos
    ; instrucciones pasan microsegundos. Seria un caso que falla una vez de
    ; cada mil, que es peor que no tenerlo.
    MOVI  R21, 1
    STORE R21, R20, 8
esperar:
    LOAD  R8, R20, 8
    BNE   R8, R0, esperar

    LOAD  R3, R20, 0           ; FB_FRONT despues
    LOAD  R4, R20, 4           ; FB_BACK despues

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
    LOAD  R6, R20, 12
    ANDI  R6, R6, 1
    BNE   R6, R0, terminar
    ORI   R10, R10, 0x0008

terminar:
    STORE R10, R19, 0
    HALT
