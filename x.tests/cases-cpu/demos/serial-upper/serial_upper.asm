; ============================================================
; serial_upper.asm - devuelve en mayuscula lo que le manden
;
; El programa interactivo mas pequeno que hace algo visible: lee un byte del
; puerto serie, si es una minuscula la convierte, y lo devuelve. Escribes
; "hola" en la consola y sale "HOLA".
;
; Corre para siempre; se para con `monitor.py halt`. Para probarlo:
;
;     .\run-demo.ps1 serial_upper
;     ..\.venv\Scripts\python.exe monitor.py console --port COM3
;
; O sin terminal, desde un script:
;
;     ..\.venv\Scripts\python.exe monitor.py send "hola" --port COM3
;
; ---- El bucle de espera, que es lo unico delicado ----
;
; NO se puede leer DATA sin mirar antes STATUS. Una lectura de DATA con la cola
; vacia devuelve cero --no bloquea, no puede bloquear: el bus MMIO se resuelve
; en un ciclo-- y el programa se pondria a mandar ceros a toda velocidad. El
; bucle mira `rx_count` en los ocho bits bajos de STATUS y solo lee cuando hay
; algo.
;
; Tampoco se mira `tx_free` antes de escribir, y eso SI es una simplificacion:
; este programa manda como mucho un byte por cada uno que recibe, asi que la
; cola de salida no puede llenarse mas que la de entrada. Un programa que
; escupa texto por su cuenta --un banner, un volcado-- tendria que mirar
; `tx_free` en los ocho bits siguientes, o perderia bytes en silencio.
;
; Puerto serie, en 0x80000200:
;   +0  DATA (leer saca, escribir mete)   +4  STATUS   +8  PEEK
;
; STATUS:  bits 7:0 bytes en la cola de entrada
;          bits 15:8 huecos en la de salida
;          bit 16 overrun
;
; Convencion de registros:
;   R20 base del dispositivo   R3  constante 0
;   R4  STATUS leido           R5  rx_count
;   R6  el byte en curso
;   R8  'a'   R9  'z'   R10 distancia entre mayuscula y minuscula
; ============================================================

.include "mmio.inc"

start:
    LI    R20, MMIO_SERIAL_BASE
    MOVI  R3, 0
    MOVI  R8, 0x61             ; 'a'
    MOVI  R9, 0x7A             ; 'z'
    MOVI  R10, 0x20            ; 'a' - 'A'

wait:
    LOAD  R4, R20, MMIO_SERIAL_STATUS_OFF           ; STATUS
    ANDI  R5, R4, 0x00FF       ; cuantos bytes hay esperando
    BEQ   R5, R3, wait         ; nada todavia

    LOAD  R6, R20, MMIO_SERIAL_DATA_OFF           ; DATA: saca un byte de la cola

    ; Solo las minusculas cambian. Todo lo demas --digitos, espacios, el
    ; salto de linea-- vuelve tal cual, que es lo que hace legible el eco.
    BLT   R6, R8, send         ; menor que 'a'
    BLT   R9, R6, send         ; mayor que 'z'
    SUB   R6, R6, R10

send:
    STORE R6, R20, MMIO_SERIAL_DATA_OFF           ; DATA: lo mete en la cola de salida
    BRA   wait
