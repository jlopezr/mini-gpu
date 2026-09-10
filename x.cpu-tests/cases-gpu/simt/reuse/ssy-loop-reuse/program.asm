; Un bucle que vuelve al mismo SSY debe reutilizar la REGION en vez de crear otra.

        GETTID R1
        ADDI   R1, R1, 100
        MOVI   R2, 0
        MOVI   R4, 128

loop:
        SSY    done
        BGE    R2, R4, done
        BGE    R2, R1, done
        ADDI   R2, R2, 1
        BRA    loop

done:
        ADDI   R3, R2, 0
        EXIT
