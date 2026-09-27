; Prueba minima de placa: dos instrucciones, CERO accesos a memoria de datos.
;
; Sirve para partir el problema en dos cuando la placa no hace nada:
;
;   R1 = 7  ->  el fetch funciona (el bufer de instrucciones sirve la linea,
;               la GPU arranca con RUN y para con HALT). Si esto va y
;               vector.asm no, el problema esta en la LSU / camino de datos.
;
;   R1 = 0  ->  no se ha ejecutado nada. Mira antes el bitstream: tiene que
;               ser el de _build/default (top_bl8). Si es el arnes de timing
;               (lsu_timing_top) no hay ni UART ni GPU.
MOVI R1, 7
BAR
HALT
