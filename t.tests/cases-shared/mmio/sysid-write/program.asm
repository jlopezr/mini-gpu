; Las siete palabras de SYSTEM son de SOLO LECTURA: escribir una da error.
.include "mmio.inc"

    LI    R1, MMIO_SYSTEM_BASE
    STORE R2, R1, MMIO_SYSTEM_SYSTEM_ID_OFF
    HALT
