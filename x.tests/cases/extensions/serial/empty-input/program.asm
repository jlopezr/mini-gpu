; Escribe sin haber leido nada, y comprueba que STATUS dice la verdad.
;
; El caso de `uppercase` solo ejercita el camino PC -> CPU. Este ejercita el
; otro, y de paso el detalle que mas facil es equivocarse: con la cola de
; entrada vacia, `rx_count` tiene que ser CERO y `tx_free` la profundidad
; entera. Si los dos campos de STATUS estuvieran cambiados de sitio, el
; programa de `uppercase` seguiria pasando --leeria 64 en vez de 0 y entraria
; al bucle igual-- y este no.
;
; R7 guarda el STATUS inicial para que el caso pueda comprobarlo como registro.

start:
    MOVHI R20, 0x8000
    ORI   R20, R20, 0x0200

    LOAD  R7, R20, 4           ; STATUS con las dos colas vacias

    ; "OK\n", sin leer nada antes.
    MOVI  R6, 0x4F
    STORE R6, R20, 0
    MOVI  R6, 0x4B
    STORE R6, R20, 0
    MOVI  R6, 0x0A
    STORE R6, R20, 0

    ; Y ahora la cola de salida tiene tres, asi que quedan 61 huecos.
    LOAD  R8, R20, 4
    HALT
