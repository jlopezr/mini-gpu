; Devuelve en mayuscula lo que le manden, y para cuando acaba la entrada.
;
; Es `19.fpga-cpu-hdmi-ls/examples/serial_upper.asm` con una diferencia: aquel
; corre para siempre porque es un demo interactivo, y este PARA cuando la cola
; de entrada se vacia. Un caso de test tiene que terminar solo.
;
; Esa parada es lo que hace el caso determinista en los dos backends: la
; entrada entera esta en la cola ANTES de arrancar --el runner la mete con
; SEND_BYTES en la placa, y como `stdin` del SerialDevice en el simulador-- asi
; que "la cola esta vacia" significa lo mismo en los dos sitios.
;
; Puerto serie: +0 DATA, +4 STATUS (bits 7:0 = bytes esperando). La direccion
; no se escribe aqui; sale del mapa (ver `mmio_v1.inc`).

.include "mmio.inc"

start:
    LI    R20, MMIO_SERIAL_BASE
    MOVI  R3, 0
    MOVI  R8, 0x61             ; 'a'
    MOVI  R9, 0x7A             ; 'z'
    MOVI  R10, 0x20            ; 'a' - 'A'

loop:
    LOAD  R4, R20, MMIO_SERIAL_STATUS_OFF
    ANDI  R5, R4, 0x00FF       ; cuantos bytes quedan
    BEQ   R5, R3, done         ; se acabo la entrada

    LOAD  R6, R20, MMIO_SERIAL_DATA_OFF   ; saca uno de la cola
    BLT   R6, R8, send         ; menor que 'a': no se toca
    BLT   R9, R6, send         ; mayor que 'z': tampoco
    SUB   R6, R6, R10

send:
    STORE R6, R20, MMIO_SERIAL_DATA_OFF
    BRA   loop

done:
    HALT
