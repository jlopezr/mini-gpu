; Bucle interior de swap_demo_fast, aislado para medir ciclos.
; 160 iteraciones = una linea de framebuffer.
start:
    MOVHI R6, 0x0001
    MOVI  R13, 0x1234
    MOVI  R3, 0
    MOVI  R25, 160
draw_word:
    STORE R13, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, draw_word
    HALT
