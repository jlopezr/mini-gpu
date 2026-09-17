; Prueba minima del camino de DATOS: cada hilo escribe un valor propio en su
; propia palabra de memoria y lo vuelve a leer.
;
; Es el escalon siguiente a smoke.asm, que no toca memoria:
;
;   smoke va y vector no  ->  el fallo esta en la LSU / SDRAM, no en el fetch.
;   los dos van           ->  camino completo vivo; ya se puede pasar a bench.
;
; Cada hilo usa la direccion 4096 + tid*4, o sea una palabra distinta por hilo y
; ninguna colision. Las 8 lanes de un warp caen en 32 bytes consecutivos, que es
; el caso COALESCIDO: la LSU v2 lo resuelve en 2 transacciones de 16 bytes.
;
; Al acabar, el hilo t deja R5 = t + 100 (lo que acaba de escribir y releer) y
; R3 = su direccion. Si R5 no coincide con R4, el dato no viaja bien.
GETTID R1                ; R1 = id global 0..63
MOVI R2, 4
MUL R3, R1, R2           ; tid*4
ADDI R3, R3, 4096        ; R3 = 4096 + tid*4, la palabra de este hilo
ADDI R4, R1, 100         ; R4 = valor propio del hilo, tid + 100
STORE R4, R3, 0
LOAD R5, R3, 0           ; R5 debe salir igual que R4
BAR
HALT
