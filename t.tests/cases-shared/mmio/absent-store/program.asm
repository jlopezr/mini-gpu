; El mismo caso en escritura: tampoco se descarta en silencio.
.include "mmio.inc"

    LI    R1, MMIO_TIMER_BASE
    STORE R2, R1, 0
    HALT
