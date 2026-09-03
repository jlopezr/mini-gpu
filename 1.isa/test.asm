; MiniISA smoke test

start:
    MOVI  R1, 10
    MOVI  R2, 20
    ADD   R3, R1, R2

loop:
    ADDI  R1, R1, 1
    BLT   R1, R2, loop

    HALT
