; Reentrar en el mismo SSY con menos lanes activas no debe sustituir el entry_mask original.

        GETTID R1
        MOVI   R2, 0
        MOVI   R3, 3

loop:
        SSY    done
        BGE    R2, R3, done
        BGE    R2, R1, done
        ADDI   R2, R2, 1
        BRA    loop

done:
        ADDI   R4, R2, 0
        EXIT
