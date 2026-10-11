; Prueba de DIVERGENCIA anidada: parte cada warp en tres caminos distintos y
; comprueba que la pila de reconvergencia los vuelve a juntar en el orden bueno.
;
; No toca memoria a proposito: lo que se mide aqui es solo el control de flujo
; SIMT (la pila SSY), no la LSU. Si esto falla, el problema esta en el SM.
;
; En esta ISA un salto DIVERGENTE necesita `SSY etiqueta` delante, marcando el
; punto donde los caminos reconvergen. Sin el, el SM para con ERROR_SIMT (0x06).
; Aqui hay dos SSY anidados, que es justo lo que se quiere estresar.
;
; Reparto por lane (ANDI ...,7 se queda con el id DENTRO del warp, asi que los
; 8 warps hacen exactamente lo mismo):
;
;   lanes 0..1  ->  lowest: R3 = 10, +1 en inner, +1 en join  ->  12
;   lanes 2..3  ->  low:    R3 = 20,        +1 en inner, +1 en join  ->  22
;   lanes 4..7  ->  alto:   R3 = 30,                    +1 en join  ->  31
;
; Acaba en EXIT, no en HALT: cada hilo termina por su cuenta.
GETTID R1
ANDI R1, R1, 7           ; R1 = lane 0..7, el warp da igual
MOVI R2, 4
SSY join                 ; los dos caminos de este BLT reconvergen en join
BLT R1, R2, low
MOVI R3, 30              ; lanes 4..7
BRA join
low:
MOVI R2, 2
SSY inner                ; segundo nivel: reconvergen en inner
BLT R1, R2, lowest
MOVI R3, 20              ; lanes 2..3
BRA inner
lowest:
MOVI R3, 10              ; lanes 0..1
inner:
ADDI R3, R3, 1           ; aqui vuelven a estar juntas las lanes 0..3
join:
ADDI R3, R3, 1           ; aqui vuelven a estar juntas las 8
BAR
EXIT
