; Un LOAD con destino R0 descarta el resultado pero hace el acceso: una
; direccion fuera de memoria sigue dando ERROR_MEMORY_ACCESS.

        MOVHI  R5, 0x7fff
        LOAD   R0, R5, 0
        MOVI   R3, 1
        HALT
