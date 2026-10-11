; BLTU y BGEU con divergencia: R1 = tid - 4 se compara con R2 = 2, un valor que
; sin signo deja a las lanes "negativas" (0..3) del lado de los grandes.

        GETTID R1
        ANDI   R1, R1, 7
        ADDI   R1, R1, -4
        MOVI   R2, 2

        SSY    join_below
        BLTU   R1, R2, below
        MOVI   R3, 3
        BRA    join_below
below:
        MOVI   R3, 7
join_below:

        SSY    join_above
        BGEU   R1, R2, above
        MOVI   R4, 3
        BRA    join_above
above:
        MOVI   R4, 7
join_above:
        HALT
