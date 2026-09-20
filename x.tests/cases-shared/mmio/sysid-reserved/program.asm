; Un offset reservado DENTRO de un bloque que si existe. SYSTEM tiene siete
; palabras (mmio.md v2 §5); la octava no es un alias, es un error.
.include "mmio.inc"

    LI    R1, MMIO_SYSTEM_BASE
    LOAD  R2, R1, 0x1C
    HALT
