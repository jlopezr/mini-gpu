; Divergencia con trabajo en ambos lados antes del join: debe aparecer exactamente un PATH.

        GETTID R1
        MOVI   R2, 4
        SSY    join

        BGE    R1, R2, taken

fallthrough:
        MOVI   R3, 11
        BRA    join

taken:
        MOVI   R3, 21
        BRA    join

join:
        EXIT
