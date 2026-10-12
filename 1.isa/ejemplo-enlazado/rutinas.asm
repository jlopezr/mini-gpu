; Biblioteca en ensamblador. MiniABI: argumento y resultado en R1, vuelta por R31.
    .text
    .globl doble
doble:
    ADD  R1, R1, R1
    JR   R31

; Nadie la llama, pero esta en el mismo objeto que doble: entra con ella.
    .globl triple
triple:
    ADD  R2, R1, R1
    ADD  R1, R2, R1
    JR   R31
