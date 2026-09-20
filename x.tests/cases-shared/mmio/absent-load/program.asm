; Un bloque SIN dispositivo da error, no cero (mmio.md v2 §4.3).
; En v1 esto era "una ranura de 256 B vacia dentro de la pagina"; en v2 es un
; bloque entero del mapa que este prototipo no implementa.
.include "mmio.inc"

    LI    R1, MMIO_TIMER_BASE
    LOAD  R2, R1, 0
    HALT
