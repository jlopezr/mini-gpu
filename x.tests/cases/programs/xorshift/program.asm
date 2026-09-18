; Genera diez pseudoaleatorios de 32 bits en 0x00100200 con xorshift32.
;
;   x ^= x << 13;  x ^= x >> 17;  x ^= x << 5
;
; Solo usa el nucleo de la ISA (XOR + SHL/SHR con registro), sin la extension
; `shift_immediate`, para que corra en cualquier CPU del repo.
    MOVHI R1, 0x1234            ; semilla = 0x12345678 (no puede ser 0)
    ORI   R1, R1, 0x5678
    MOVHI R2, 0x0010            ; destino = 0x00100200
    ADDI  R2, R2, 0x0200
    MOVI  R3, 10                ; contador
    MOVI  R10, 13               ; cantidades de desplazamiento
    MOVI  R11, 17
    MOVI  R12, 5
loop:
    SHL   R4, R1, R10
    XOR   R1, R1, R4
    SHR   R4, R1, R11
    XOR   R1, R1, R4
    SHL   R4, R1, R12
    XOR   R1, R1, R4
    STORE R1, R2, 0
    ADDI  R2, R2, 4
    ADDI  R3, R3, -1
    BNE   R3, R0, loop
    HALT
